import { BrowserRouter, Routes, Route } from 'react-router-dom';
import DashboardLayout from './layouts/DashboardLayout';
import Dashboard from './pages/Dashboard';
import Shopping from './pages/Shopping';
import Negotiation from './pages/Negotiation';
import Payment from './pages/Payment';

function App() {
  return (
    <BrowserRouter>
      <DashboardLayout>
        <Routes>
          <Route path="/" element={<Dashboard />} />
          <Route path="/shopping" element={<Shopping />} />
          <Route path="/negotiation" element={<Negotiation />} />
          <Route path="/payment" element={<Payment />} />
        </Routes>
      </DashboardLayout>
    </BrowserRouter>
  );
}

export default App;
