import React from 'react';
import { Link, NavLink } from 'react-router-dom';
import { Shield, Server, Terminal } from 'lucide-react';
import './DashboardLayout.css';

const GithubIcon = (props: React.SVGProps<SVGSVGElement>) => (
  <svg 
    viewBox="0 0 24 24" 
    width="24" 
    height="24" 
    stroke="currentColor" 
    strokeWidth="2" 
    fill="none" 
    strokeLinecap="round" 
    strokeLinejoin="round" 
    {...props}
  >
    <path d="M9 19c-5 1.5-5-2.5-7-3m14 6v-3.87a3.37 3.37 0 0 0-.94-2.61c3.14-.35 6.44-1.54 6.44-7A5.44 5.44 0 0 0 20 4.77 5.07 5.07 0 0 0 19.91 1S18.73.65 16 2.48a13.38 13.38 0 0 0-7 0C6.27.65 5.09 1 5.09 1A5.07 5.07 0 0 0 5 4.77a5.44 5.44 0 0 0-1.5 3.78c0 5.42 3.3 6.61 6.44 7A3.37 3.37 0 0 0 9 18.13V22" />
  </svg>
);

interface DashboardLayoutProps {
  children: React.ReactNode;
}

export default function DashboardLayout({ children }: DashboardLayoutProps) {
  return (
    <div className="layout-wrapper">
      {/* Top Header */}
      <header className="layout-header">
        <div className="header-container">
          <Link to="/" className="header-logo-section">
            <Shield className="logo-icon animate-pulse" />
            <span className="logo-text">SETU</span>
            <span className="logo-divider">/</span>
            <span className="logo-subtext">AI Trust Layer</span>
          </Link>

          <div className="header-status-badge">
            <span className="status-dot"></span>
            <span className="status-text">AGENT GATEWAY: SECURED</span>
          </div>

          <nav className="header-nav">
            <NavLink to="/" className={({ isActive }) => `nav-link ${isActive ? 'active' : ''}`}>Dashboard</NavLink>
            <NavLink to="/trust" className={({ isActive }) => `nav-link ${isActive ? 'active' : ''}`}>Trust Center</NavLink>
            <NavLink to="/orders" className={({ isActive }) => `nav-link ${isActive ? 'active' : ''}`}>Orders</NavLink>
            <NavLink to="/transactions" className={({ isActive }) => `nav-link ${isActive ? 'active' : ''}`}>Transactions</NavLink>
          </nav>

          <div className="header-actions">
            <a 
              href="https://github.com/THILAKESWARAN07/SETU-AI-to-AI-agent" 
              target="_blank" 
              rel="noopener noreferrer"
              className="github-link"
            >
              <GithubIcon className="action-icon" />
            </a>
          </div>
        </div>
      </header>

      {/* Main Content Area */}
      <main className="layout-main container">
        {children}
      </main>

      {/* Footer */}
      <footer className="layout-footer">
        <div className="footer-container container">
          <div className="footer-left">
            <Server className="footer-icon" />
            <span>SQLite DB: connected</span>
            <span className="footer-dot">•</span>
            <Terminal className="footer-icon" />
            <span>Policy Version: policy_v1.0</span>
          </div>
          <div className="footer-right">
            <span>© {new Date().getFullYear()} SETU Commerce Trust. All rights reserved.</span>
          </div>
        </div>
      </footer>
    </div>
  );
}
