import { BrowserRouter, Routes, Route } from 'react-router-dom';
import DashboardLayout from './layouts/DashboardLayout';
import Dashboard from './pages/Dashboard';
import Shopping from './pages/Shopping';
import Negotiation from './pages/Negotiation';
import Payment from './pages/Payment';
import Transactions from './pages/Transactions';
import TransactionDetails from './pages/TransactionDetails';

function App() {
  return (
    <BrowserRouter>
      <DashboardLayout>
        <Routes>
          <Route path="/" element={<Dashboard />} />
          <Route path="/shopping" element={<Shopping />} />
          <Route path="/negotiation" element={<Negotiation />} />
          <Route path="/payment" element={<Payment />} />
          <Route path="/transactions" element={<Transactions />} />
          <Route path="/transactions/:id" element={<TransactionDetails />} />
        </Routes>
      </DashboardLayout>
    </BrowserRouter>
  );
}

export default App;
