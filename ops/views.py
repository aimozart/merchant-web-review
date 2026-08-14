from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from . import faults, infra_faults, network_faults
from .models import Ticket
from .serializers import TicketSerializer
from .tasks import replenish_ticket


class TicketViewSet(viewsets.ModelViewSet):
    """
    The ticket queue — filed either automatically (hourly health check,
    fault-injection practice) or manually. `inject`, `verify`, and `close` are the
    three moves in the "you break it, I fix it" practice loop: inject a fault,
    fix the real underlying state, verify (which re-checks reality, not just the
    ticket's own status field), then close.
    """

    queryset = Ticket.objects.order_by("-created_at")
    serializer_class = TicketSerializer
    filterset_fields = ["status", "priority", "category", "source"]

    @action(detail=False, methods=["post"])
    def inject(self, request):
        tier = int(request.data.get("tier", 1))
        fault_key = request.data.get("fault_key")
        registry, inject_one, inject_random = {
            1: (faults.FAULTS, faults.inject_fault, faults.inject_random_fault),
            2: (infra_faults.INFRA_FAULTS, infra_faults.inject_infra_fault, infra_faults.inject_random_infra_fault),
            3: (network_faults.NETWORK_FAULTS, network_faults.inject_network_fault, network_faults.inject_random_network_fault),
        }[tier]

        if fault_key:
            if fault_key not in registry:
                return Response(
                    {"error": f"Unknown fault_key for tier {tier}. Choices: {list(registry)}"},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            ticket = inject_one(fault_key)
        else:
            ticket = inject_random()
        return Response(TicketSerializer(ticket).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["post"])
    def verify(self, request, pk=None):
        ticket = self.get_object()
        if ticket.fault_key in faults.FAULTS:
            resolved = faults.verify_fix(ticket)
        elif ticket.fault_key in infra_faults.INFRA_FAULTS:
            resolved = infra_faults.verify_infra_fix(ticket)
        elif ticket.fault_key in network_faults.NETWORK_FAULTS:
            resolved = network_faults.verify_network_fix(ticket)
        else:
            return Response(
                {"error": "This ticket wasn't filed by the fault-injection tool — nothing to verify."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        ticket.refresh_from_db()
        return Response({"resolved": resolved, "ticket": TicketSerializer(ticket).data})

    @action(detail=True, methods=["post"])
    def close(self, request, pk=None):
        ticket = self.get_object()
        if ticket.status != "resolved":
            return Response(
                {"error": "Only a 'resolved' ticket can be closed — verify the fix first."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        ticket.status = "closed"
        ticket.resolution_notes = request.data.get("resolution_notes", ticket.resolution_notes)
        ticket.save(update_fields=["status", "resolution_notes"])
        replenish_ticket.delay()
        return Response(TicketSerializer(ticket).data)
