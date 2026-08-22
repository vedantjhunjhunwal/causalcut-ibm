import React, { useState, useEffect } from 'react';
import { ShieldCheck, AlertTriangle, CheckCircle, XCircle, HardHat, Wind, FileText, Clock, RefreshCw } from 'lucide-react';
import { api } from '../../api';

export default function ComplianceReportView() {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);
  const [filter, setFilter] = useState('ALL');
  const [checking, setChecking] = useState(false);
  
  const fetchCompliance = async () => {
    try {
      setLoading(true);
      setError(false);
      
      let result;
      if (api.agentCompliance) {
        result = await api.agentCompliance();
      } else {
        // Fallback mock data if API method doesn't exist yet
        await new Promise(resolve => setTimeout(resolve, 800));
        result = {
          overall_status: 'WARNING',
          last_checked: new Date().toISOString(),
          summary: { compliant: 24, warnings: 3, violations: 1 },
          items: [
            { id: 1, category: 'PPE', name: 'Helmet Detection', regulation: 'OISD-STD-116 Clause 4.3', status: 'compliant', description: 'All workers in Zone A wearing hardhats.', current: '100%', required: '100%' },
            { id: 2, category: 'Gas Monitoring', name: 'H2S Levels', regulation: 'OSHA 1910.1000', status: 'warning', description: 'H2S detected near threshold limit in Gas Treatment.', current: '8 ppm', required: '< 10 ppm', remediation: 'Increase ventilation in Zone C' },
            { id: 3, category: 'Permits', name: 'Hot Work Permit', regulation: 'IS 5216', status: 'violation', description: 'Active hot work detected without valid permit in Battery 3.', current: 'Missing', required: 'Valid Permit', remediation: 'Halt work immediately and issue permit' },
            { id: 4, category: 'Ventilation', name: 'Airflow Rate', regulation: 'FACTORY ACT SEC 13', status: 'compliant', description: 'Airflow maintained at optimal levels.', current: '15 ACH', required: '> 10 ACH' }
          ]
        };
      }
      setData(result);
    } catch (e) {
      console.error(e);
      setError(true);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchCompliance();
  }, []);

  const runCheck = async () => {
    setChecking(true);
    await fetchCompliance();
    setChecking(false);
  };

  const getIcon = (category) => {
    switch (category) {
      case 'PPE': return <HardHat size={16} />;
      case 'Gas Monitoring': return <Wind size={16} />;
      case 'Permits': return <FileText size={16} />;
      case 'Ventilation': return <Wind size={16} />;
      default: return <ShieldCheck size={16} />;
    }
  };

  if (error) {
    return (
      <div className="page-canvas">
        <div style={{ textAlign: 'center', marginTop: '50px', color: '#ef4444' }}>
          <AlertTriangle size={48} style={{ margin: '0 auto 16px' }} />
          <h2 style={{ fontSize: '20px', fontWeight: 600 }}>Unable to load compliance report</h2>
          <button className="action-btn" onClick={fetchCompliance} style={{ marginTop: '16px' }}>Retry</button>
        </div>
      </div>
    );
  }

  const filters = ['ALL', 'PPE', 'Gas Monitoring', 'Permits', 'Ventilation', 'Worker Safety'];
  
  const filteredItems = data?.items?.filter(item => filter === 'ALL' || item.category === filter) || [];

  return (
    <div className="page-canvas">
      {/* Header */}
      <div className="page-header">
        <div>
          <div className="breadcrumbs">COMPLIANCE / REGULATORY [C]</div>
          <h1 className="page-title" style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
            <ShieldCheck size={28} color="#0f766e" />
            Regulatory Compliance
          </h1>
          <div className="page-subtitle">
            Automated monitoring of OISD, OSHA, and internal safety standards.
          </div>
        </div>
        <button className="action-btn teal" onClick={runCheck} disabled={checking || loading}>
          <RefreshCw size={14} className={checking ? 'animate-spin' : ''} />
          <span>{checking ? 'Running Check...' : 'Run Check Now'}</span>
        </button>
      </div>

      {loading ? (
        <div style={{ padding: '40px', textAlign: 'center', color: '#64748b' }}>
          Loading compliance data...
        </div>
      ) : !data ? (
        <div className="panel-box" style={{ padding: '40px', textAlign: 'center' }}>
          <div style={{ color: '#64748b', marginBottom: '16px' }}>No compliance data available. Run a check to get started.</div>
          <button className="action-btn primary" onClick={runCheck}>Run Check</button>
        </div>
      ) : (
        <>
          {/* Summary Cards */}
          <div className="kpi-grid cols-3">
            <div className="kpi-card accent-teal">
              <div className="kpi-title">COMPLIANT</div>
              <div className="kpi-value" style={{ color: '#0d9488' }}>{data.summary.compliant}</div>
            </div>
            <div className="kpi-card accent-amber">
              <div className="kpi-title">WARNINGS</div>
              <div className="kpi-value" style={{ color: '#d97706' }}>{data.summary.warnings}</div>
            </div>
            <div className="kpi-card accent-red">
              <div className="kpi-title">VIOLATIONS</div>
              <div className="kpi-value" style={{ color: '#e11d48' }}>{data.summary.violations}</div>
            </div>
          </div>

          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '20px' }}>
            <div className="filter-pills-row" style={{ margin: 0 }}>
              {filters.map(f => (
                <button 
                  key={f} 
                  className={`filter-pill ${filter === f ? 'active' : ''}`}
                  onClick={() => setFilter(f)}
                >
                  {f}
                </button>
              ))}
            </div>
            
            <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
              <div style={{ fontSize: '12px', color: '#64748b', display: 'flex', alignItems: 'center', gap: '4px' }}>
                <Clock size={14} />
                Last checked: {new Date(data.last_checked).toLocaleString()}
              </div>
              <span className={`badge-pill ${data.overall_status === 'COMPLIANT' ? 'low' : data.overall_status === 'WARNING' ? 'medium' : 'high'}`} style={{ fontSize: '12px', padding: '4px 10px' }}>
                OVERALL: {data.overall_status}
              </span>
            </div>
          </div>

          {/* Items */}
          <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
            {filteredItems.map(item => (
              <div key={item.id} className="panel-box" style={{ padding: '16px', display: 'flex', gap: '16px', alignItems: 'flex-start' }}>
                <div style={{ 
                  width: '40px', height: '40px', borderRadius: '8px', 
                  backgroundColor: item.status === 'compliant' ? '#ecfdf5' : item.status === 'warning' ? '#fffbeb' : '#fef2f2',
                  color: item.status === 'compliant' ? '#059669' : item.status === 'warning' ? '#d97706' : '#e11d48',
                  display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0
                }}>
                  {item.status === 'compliant' ? <CheckCircle size={20} /> : item.status === 'warning' ? <AlertTriangle size={20} /> : <XCircle size={20} />}
                </div>
                
                <div style={{ flex: 1 }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: '8px' }}>
                    <div>
                      <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '4px' }}>
                        <span style={{ fontSize: '11px', fontWeight: 700, color: '#64748b', display: 'flex', alignItems: 'center', gap: '4px', textTransform: 'uppercase' }}>
                          {getIcon(item.category)} {item.category}
                        </span>
                        <span style={{ fontSize: '10px', backgroundColor: '#f1f5f9', padding: '2px 6px', borderRadius: '4px', color: '#475569', fontWeight: 600 }}>
                          {item.regulation}
                        </span>
                      </div>
                      <h3 style={{ fontSize: '15px', fontWeight: 700, color: '#0f172a', margin: 0 }}>{item.name}</h3>
                    </div>
                    <span className={`badge-pill ${item.status === 'compliant' ? 'low' : item.status === 'warning' ? 'medium' : 'high'}`}>
                      {item.status.toUpperCase()}
                    </span>
                  </div>
                  
                  <p style={{ fontSize: '13px', color: '#475569', margin: '0 0 12px 0', lineHeight: 1.5 }}>
                    {item.description}
                  </p>
                  
                  <div style={{ display: 'flex', gap: '24px', fontSize: '12px', backgroundColor: '#f8fafc', padding: '10px 12px', borderRadius: '4px' }}>
                    <div>
                      <span style={{ color: '#64748b', marginRight: '6px' }}>Current:</span>
                      <span style={{ fontWeight: 600, color: '#0f172a' }}>{item.current}</span>
                    </div>
                    <div>
                      <span style={{ color: '#64748b', marginRight: '6px' }}>Required:</span>
                      <span style={{ fontWeight: 600, color: '#0f172a' }}>{item.required}</span>
                    </div>
                    {item.remediation && (
                      <div style={{ marginLeft: 'auto', color: item.status === 'warning' ? '#b45309' : '#be123c', fontWeight: 600, display: 'flex', alignItems: 'center', gap: '4px' }}>
                        <AlertTriangle size={12} />
                        Remediation: {item.remediation}
                      </div>
                    )}
                  </div>
                </div>
              </div>
            ))}
            
            {filteredItems.length === 0 && (
              <div style={{ padding: '30px', textAlign: 'center', color: '#64748b', backgroundColor: '#f8fafc', borderRadius: '4px', border: '1px solid #e2e8f0' }}>
                No compliance items match the selected filter.
              </div>
            )}
          </div>
        </>
      )}
    </div>
  );
}
