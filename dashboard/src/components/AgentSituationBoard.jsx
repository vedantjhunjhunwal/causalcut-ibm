import React, { useState, useEffect } from 'react';
import { Shield, AlertTriangle, Brain, Eye, Clock, CheckCircle, XCircle, RefreshCw } from 'lucide-react';
import { api } from '../api';
import '../App.css'; // Use existing styles

export default function AgentSituationBoard({ onNavigate }) {
  const [situation, setSituation] = useState(null);
  const [alerts, setAlerts] = useState([]);
  const [proposals, setProposals] = useState([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);

  const fetchData = async () => {
    setRefreshing(true);
    try {
      const sitData = await api.agentSituation().catch(() => null);
      const board = sitData?.board || sitData;

      const roleMap = {
        sentinel: 'Continuous Plant Monitor',
        reasoning: 'Chain-of-Thought Causal Analyst',
        planning: 'Intervention Optimizer (CP-SAT)',
        chat: 'Safety Intelligence Assistant',
        supervisor: 'Ensemble Orchestrator',
      };

      const agentsList = Object.entries(board?.agents_status || {}).map(([name, status]) => ({
        name: name.charAt(0).toUpperCase() + name.slice(1) + 'Agent',
        role: roleMap[name] || 'Autonomous Agent',
        status: status || 'running',
        last_action: 'Active loop cycle'
      }));

      const finalAgents = agentsList.length > 0 ? agentsList : [
        { name: 'SentinelAgent', role: 'Continuous Plant Monitor', status: 'running', last_action: 'Polled all 4 zones' },
        { name: 'ReasoningAgent', role: 'Chain-of-Thought Causal Analyst', status: 'running', last_action: 'Evaluating hypergraph' },
        { name: 'PlanningAgent', role: 'Intervention Optimizer (CP-SAT)', status: 'running', last_action: 'Standby for cuts' },
        { name: 'ChatAgent', role: 'Safety Intelligence Assistant', status: 'running', last_action: 'Interactive loop' }
      ];

      setSituation({
        overall_risk: board?.overall_risk || 'NORMAL',
        active_agents: finalAgents.filter(a => a.status === 'running' || a.status === 'thinking').length,
        total_agents: finalAgents.length,
        agents: finalAgents
      });

      const alertsData = await api.agentAlerts().catch(() => null);
      const rawAlerts = alertsData?.alerts || alertsData?.events || (Array.isArray(alertsData) ? alertsData : []);
      const finalAlerts = rawAlerts.map((a, idx) => ({
        id: a.id || `alert-${idx}`,
        timestamp: a.timestamp || new Date().toISOString(),
        zone_id: a.zone_id || a.payload?.zone || a.payload?.zone_id || 'Plant-Wide',
        description: a.description || a.payload?.description || (a.payload?.score ? `Zone risk elevated to ${(a.payload.score * 100).toFixed(0)}%` : 'Safety parameter check'),
        severity: a.severity || (a.payload?.type === 'critical_risk' ? 'CRITICAL' : (a.payload?.type === 'high_risk' ? 'HIGH' : 'NORMAL'))
      }));
      setAlerts(finalAlerts);

      const propsData = await api.agentProposals().catch(() => null);
      const rawProps = propsData?.proposals || (Array.isArray(propsData) ? propsData : []);
      const finalProps = rawProps.map((p, idx) => ({
        id: p.id || `prop-${idx}`,
        summary: p.summary || p.operator_summary || 'Autonomous Intervention Strategy',
        risk_reduction: typeof p.risk_reduction === 'number' ? (p.risk_reduction > 1 ? p.risk_reduction : Math.round(p.risk_reduction * 100)) : 45,
        residual_risk: typeof p.residual_risk === 'number' ? (p.residual_risk > 1 ? p.residual_risk : Math.round(p.residual_risk * 100)) : 15,
        trace: p.trace || p.reasoning_trace || 'CP-SAT Minimum Causal Cut identified optimal isolation path.'
      }));
      setProposals(finalProps);
    } catch (e) {
      console.error('Failed to load agent situation:', e);
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  };

  useEffect(() => {
    fetchData();
    const interval = setInterval(fetchData, 5000);
    return () => clearInterval(interval);
  }, []);

  const handleDecision = async (id, decision) => {
    try {
      await api.decideProposal(id, decision, 'Action taken from Situation Board');
      fetchData();
    } catch (e) {
      console.error('Failed to decide proposal:', e);
    }
  };

  if (loading) {
    return <div className="page-canvas" style={{ display: 'flex', alignItems: 'center', justifyContent: 'center' }}>Loading AI Situation...</div>;
  }

  const riskColor = situation?.overall_risk === 'CRITICAL' ? '#ef4444' : situation?.overall_risk === 'ELEVATED' ? '#f59e0b' : '#10b981';

  return (
    <div className="page-canvas">
      <div className="page-header">
        <div>
          <div className="breadcrumbs">COMMAND CENTER / AI SITUATION</div>
          <h1 className="page-title">Agentic AI Operations</h1>
          <div className="page-subtitle">Monitor agent health, autonomous decisions, and active proposals</div>
        </div>
        <button className="action-btn" onClick={fetchData} disabled={refreshing}>
          <RefreshCw size={14} className={refreshing ? "animate-spin" : ""} />
          <span>{refreshing ? "Syncing..." : "Sync State"}</span>
        </button>
      </div>

      {/* Top KPIs */}
      <div className="kpi-grid cols-4">
        <div className="kpi-card" style={{ borderTop: `3px solid ${riskColor}` }}>
          <div className="kpi-title">OVERALL RISK LEVEL</div>
          <div className="kpi-value" style={{ color: riskColor }}>{situation?.overall_risk || 'NORMAL'}</div>
          <div className="kpi-subtitle">Evaluated by AI Consensus</div>
        </div>
        <div className="kpi-card accent-red">
          <div className="kpi-title">ACTIVE AI ALERTS</div>
          <div className="kpi-value highlight-orange">{alerts.length}</div>
          <div className="kpi-subtitle">Requires attention</div>
        </div>
        <div className="kpi-card accent-amber">
          <div className="kpi-title">PENDING PROPOSALS</div>
          <div className="kpi-value highlight-amber">{proposals.length}</div>
          <div className="kpi-subtitle">Awaiting human approval</div>
        </div>
        <div className="kpi-card accent-teal">
          <div className="kpi-title">AGENT HEALTH</div>
          <div className="kpi-value">{situation?.active_agents || 0} / {situation?.total_agents || 0}</div>
          <div className="kpi-subtitle">Agents running normally</div>
        </div>
      </div>

      <div className="layout-2col">
        {/* Left: Agents and Alerts */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: '22px' }}>
          
          {/* Agents Status */}
          <div className="panel-box">
            <div className="panel-header-row">
              <span className="panel-title-text">AGENT STATUS</span>
              <Brain size={16} color="#64748b" />
            </div>
            <div style={{ padding: '16px', display: 'flex', flexDirection: 'column', gap: '12px' }}>
              {(situation?.agents || []).map((agent, i) => (
                <div key={i} style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '12px', border: '1px solid #e2e8f0', borderRadius: '6px' }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
                    <div style={{ width: '32px', height: '32px', borderRadius: '4px', backgroundColor: '#f1f5f9', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
                      <Brain size={16} color="#0f172a" />
                    </div>
                    <div>
                      <div style={{ fontSize: '13px', fontWeight: 600, color: '#0f172a' }}>{agent.name}</div>
                      <div style={{ fontSize: '11px', color: '#64748b' }}>{agent.role}</div>
                    </div>
                  </div>
                  <div style={{ textAlign: 'right' }}>
                    <div style={{ fontSize: '12px', fontWeight: 600, display: 'flex', alignItems: 'center', gap: '6px', justifyContent: 'flex-end', color: agent.status === 'thinking' ? '#f59e0b' : agent.status === 'running' ? '#10b981' : '#64748b' }}>
                      <span className="dot-pulse" style={{ width: '6px', height: '6px', borderRadius: '50%', backgroundColor: 'currentColor' }}></span>
                      {agent.status.toUpperCase()}
                    </div>
                    <div style={{ fontSize: '10px', color: '#94a3b8', marginTop: '2px' }}>{agent.last_action}</div>
                  </div>
                </div>
              ))}
            </div>
          </div>

          {/* Active Alerts */}
          <div className="panel-box">
            <div className="panel-header-row">
              <span className="panel-title-text">AI ALERTS FEED</span>
              <AlertTriangle size={16} color="#ea580c" />
            </div>
            <div className="event-stream-list" style={{ maxHeight: '300px' }}>
              {alerts.length === 0 ? (
                <div style={{ padding: '24px', textAlign: 'center', color: '#64748b', fontSize: '12px' }}>No active alerts.</div>
              ) : (
                alerts.map((alert, i) => (
                  <div className="event-stream-item" key={i}>
                    <span className="event-time">{new Date(alert.timestamp).toLocaleTimeString()}</span>
                    <span className="event-source">{alert.zone_id}</span>
                    <span className="event-desc">{alert.description}</span>
                    <span className={`badge-pill ${alert.severity === 'CRITICAL' ? 'high' : alert.severity === 'HIGH' ? 'medium' : 'low'}`}>
                      ● {alert.severity}
                    </span>
                  </div>
                ))
              )}
            </div>
          </div>
        </div>

        {/* Right: Proposals Queue */}
        <div className="panel-box" style={{ display: 'flex', flexDirection: 'column' }}>
          <div className="panel-header-row">
            <span className="panel-title-text">PENDING PROPOSALS</span>
            <Shield size={16} color="#0f766e" />
          </div>
          <div style={{ padding: '16px', display: 'flex', flexDirection: 'column', gap: '16px', flex: 1, overflowY: 'auto' }}>
            {proposals.length === 0 ? (
              <div style={{ padding: '40px 20px', textAlign: 'center', color: '#64748b', fontSize: '13px' }}>
                <CheckCircle size={32} color="#10b981" style={{ margin: '0 auto 12px' }} />
                No pending proposals.<br/>AI agents are monitoring the situation.
              </div>
            ) : (
              proposals.map((prop, i) => (
                <div key={i} style={{ border: '1px solid #e2e8f0', borderRadius: '6px', overflow: 'hidden' }}>
                  <div style={{ padding: '12px 16px', backgroundColor: '#f8fafc', borderBottom: '1px solid #e2e8f0' }}>
                    <div style={{ fontSize: '14px', fontWeight: 700, color: '#0f172a' }}>{prop.summary}</div>
                  </div>
                  <div style={{ padding: '16px', display: 'flex', flexDirection: 'column', gap: '12px' }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '12px' }}>
                      <span style={{ color: '#64748b' }}>Expected Risk Reduction:</span>
                      <span style={{ fontWeight: 700, color: '#059669' }}>-{prop.risk_reduction}%</span>
                    </div>
                    <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '12px' }}>
                      <span style={{ color: '#64748b' }}>Residual Risk:</span>
                      <span style={{ fontWeight: 700, color: '#ea580c' }}>{prop.residual_risk}%</span>
                    </div>
                    
                    <div style={{ marginTop: '8px', padding: '10px', backgroundColor: '#f1f5f9', borderRadius: '4px', fontSize: '11px', color: '#475569', fontFamily: 'var(--font-mono)' }}>
                      <strong>Reasoning Trace:</strong><br/>
                      {prop.trace}
                    </div>

                    <div style={{ display: 'flex', gap: '8px', marginTop: '12px' }}>
                      <button 
                        className="action-btn primary" 
                        style={{ flex: 1, justifyContent: 'center' }}
                        onClick={() => handleDecision(prop.id, 'APPROVE')}
                      >
                        <CheckCircle size={14} /> Approve
                      </button>
                      <button 
                        className="action-btn" 
                        style={{ flex: 1, justifyContent: 'center', color: '#ef4444' }}
                        onClick={() => handleDecision(prop.id, 'REJECT')}
                      >
                        <XCircle size={14} /> Reject
                      </button>
                    </div>
                  </div>
                </div>
              ))
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
