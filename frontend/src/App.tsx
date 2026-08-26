import { BrowserRouter, Routes, Route } from 'react-router-dom';
import DashboardLayout from './layouts/DashboardLayout';
import Dashboard from './pages/Dashboard';
import Shopping from './pages/Shopping';
import Negotiation from './pages/Negotiation';
import Payment from './pages/Payment';
import Transactions from './pages/Transactions';
import TransactionDetails from './pages/TransactionDetails';
import TrustCenter from './pages/TrustCenter';
import Orders from './pages/Orders';
import OrderDetails from './pages/OrderDetails';

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
          <Route path="/trust" element={<TrustCenter />} />
          <Route path="/orders" element={<Orders />} />
          <Route path="/orders/:id" element={<OrderDetails />} />
        </Routes>
      </DashboardLayout>
    </BrowserRouter>
  );
}

export default App;

