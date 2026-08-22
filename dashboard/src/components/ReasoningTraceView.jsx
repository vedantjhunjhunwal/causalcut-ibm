import React from 'react';
import { Brain, ChevronRight, Wrench, AlertTriangle } from 'lucide-react';

export default function ReasoningTraceView({ trace, factors, confidence }) {
  if (!trace || trace.length === 0) {
    return (
      <div className="panel-box" style={{ padding: '24px', textAlign: 'center', color: '#64748b' }}>
        <Brain size={32} style={{ margin: '0 auto 12px auto', opacity: 0.5 }} />
        <div style={{ fontSize: '14px', fontWeight: 600 }}>No reasoning trace available</div>
      </div>
    );
  }

  // Determine confidence color
  let confColor = '#ef4444'; // red
  if (confidence > 0.7) confColor = '#10b981'; // green
  else if (confidence >= 0.4) confColor = '#f59e0b'; // amber

  return (
    <div className="panel-box">
      <div className="panel-header-row">
        <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
          <Brain size={16} color="#0284c7" />
          <span className="panel-title-text">Reasoning Trace</span>
        </div>
      </div>
      
      <div style={{ padding: '20px' }}>
        {/* Timeline */}
        <div style={{ position: 'relative', paddingLeft: '12px' }}>
          {trace.map((step, idx) => {
            const isToolCall = step.toLowerCase().includes('tool') || step.toLowerCase().includes('call') || step.toLowerCase().includes('search');
            return (
              <div key={idx} style={{ display: 'flex', gap: '16px', marginBottom: idx === trace.length - 1 ? '24px' : '16px', position: 'relative' }}>
                {idx !== trace.length - 1 && (
                  <div style={{ position: 'absolute', left: '12px', top: '24px', bottom: '-16px', width: '2px', backgroundColor: '#e2e8f0' }} />
                )}
                
                <div style={{ 
                  width: '24px', height: '24px', borderRadius: '50%', backgroundColor: '#0284c7', color: 'white',
                  display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: '12px', fontWeight: 700,
                  zIndex: 1, flexShrink: 0
                }}>
                  {idx + 1}
                </div>
                
                <div style={{ flex: 1, backgroundColor: '#f8fafc', padding: '12px', borderRadius: '6px', border: '1px solid #e2e8f0', fontSize: '13px', color: '#334155' }}>
                  {step}
                  {isToolCall && (
                    <div style={{ display: 'flex', alignItems: 'center', gap: '4px', marginTop: '8px', fontSize: '11px', color: '#ea580c', fontWeight: 600 }}>
                      <Wrench size={12} />
                      <span>TOOL CALL</span>
                    </div>
                  )}
                </div>
              </div>
            );
          })}
        </div>
        
        {/* Factors */}
        {factors && factors.length > 0 && (
          <div style={{ marginBottom: '24px' }}>
            <div className="kpi-title" style={{ marginBottom: '12px' }}>CONTRIBUTING FACTORS</div>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))', gap: '12px' }}>
              {factors.map((factor, idx) => (
                <div key={idx} style={{ padding: '12px', borderRadius: '6px', border: '1px solid #e2e8f0', backgroundColor: '#ffffff' }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '8px' }}>
                    <span style={{ fontSize: '13px', fontWeight: 600, color: '#0f172a' }}>{factor.name}</span>
                    <span className={`badge-pill ${factor.severity?.toLowerCase() || 'medium'}`}>● {factor.severity || 'MEDIUM'}</span>
                  </div>
                  <div style={{ fontSize: '11px', color: '#64748b', display: 'flex', alignItems: 'center', gap: '4px' }}>
                    <AlertTriangle size={12} />
                    <span>Zone: {factor.zone}</span>
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}
        
        {/* Confidence Meter */}
        {confidence !== null && (
          <div>
            <div className="kpi-title" style={{ marginBottom: '8px', display: 'flex', justifyContent: 'space-between' }}>
              <span>MODEL CONFIDENCE</span>
              <span style={{ color: confColor, fontWeight: 700, fontSize: '12px' }}>{Math.round(confidence * 100)}%</span>
            </div>
            <div style={{ width: '100%', height: '8px', backgroundColor: '#e2e8f0', borderRadius: '4px', overflow: 'hidden' }}>
              <div style={{ width: `${Math.round(confidence * 100)}%`, height: '100%', backgroundColor: confColor, borderRadius: '4px', transition: 'width 0.5s ease' }} />
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
