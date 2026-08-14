import { NavLink, Route, Routes } from "react-router-dom";
import "./App.css";
import Dashboard from "./pages/Dashboard";
import MerchantDetail from "./pages/MerchantDetail";
import Tickets from "./pages/Tickets";

export default function App() {
  return (
    <div className="app-shell">
      <header className="topnav">
        <span className="brand">Merchant Web Review</span>
        <nav>
          <NavLink to="/" end className={({ isActive }) => (isActive ? "active" : "")}>
            Merchants
          </NavLink>
          <NavLink to="/tickets" className={({ isActive }) => (isActive ? "active" : "")}>
            Ops / Tickets
          </NavLink>
        </nav>
      </header>
      <main>
        <Routes>
          <Route path="/" element={<Dashboard />} />
          <Route path="/merchants/:id" element={<MerchantDetail />} />
          <Route path="/tickets" element={<Tickets />} />
        </Routes>
      </main>
    </div>
  );
}
