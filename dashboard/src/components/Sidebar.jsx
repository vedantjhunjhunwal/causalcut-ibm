import React from "react";
import {
  LayoutDashboard,
  Layers,
  GitBranch,
  Target,
  PlayCircle,
  Radio,
  Network,
  AlertTriangle,
  ClipboardCheck,
  FileSearch,
  Cpu,
  Activity,
  Settings,
  ChevronDown,
  Bot,
} from "lucide-react";

export default function Sidebar({
  activeTab,
  setActiveTab,
  pendingApprovalsCount = 2,
  operator,
  isChatOpen = false,
  onToggleChat,
}) {
  const currentOperator = operator || {
    name: "N. Sharma",
    role: "SHIFT OFFICER · B",
    initials: "NS",
  };

  const navSections = [
    {
      group: "COMMAND",
      items: [
        { id: "command-center", label: "Command center", icon: LayoutDashboard },
        { id: "plant-state", label: "Plant state", icon: Layers },
        { id: "risk-paths", label: "Risk paths", icon: GitBranch },
        { id: "interventions", label: "Interventions", icon: Target },
        { id: "simulation", label: "Simulation", icon: PlayCircle },
      ],
    },
    {
      group: "OPERATIONS",
      items: [
        { id: "live-events", label: "Live events", icon: Radio },
        { id: "scenarios", label: "Scenarios", icon: Network },
        { id: "incidents", label: "Incidents", icon: AlertTriangle },
      ],
    },
    {
      group: "GOVERNANCE",
      items: [
        { id: "approvals", label: "Approvals", icon: ClipboardCheck, badge: pendingApprovalsCount },
        { id: "audit-log", label: "Audit log", icon: FileSearch },
        { id: "models", label: "Models", icon: Cpu },
      ],
    },
    {
      group: "AI AGENT",
      items: [
        { id: "ai-agent", label: "Safety Intelligence", icon: Bot },
      ],
    },
    {
      group: "SYSTEM",
      items: [
        { id: "system-health", label: "System health", icon: Activity },
        { id: "settings", label: "Settings", icon: Settings },
      ],
    },
  ];

  return (
    <aside className="sidebar">
      {/* Brand Header */}
      <div className="sidebar-header">
        <div className="brand-logo-box">C</div>
        <div className="brand-info">
          <span className="brand-name">CAUSALCUT</span>
          <span className="brand-sub">Safety Intelligence</span>
        </div>
      </div>

      {/* Navigation Sections */}
      <div className="sidebar-nav">
        {navSections.map((section) => (
          <div key={section.group} className="nav-group">
            <div className="nav-group-title">{section.group}</div>
            <div className="nav-item-list">
              {section.items.map((item) => {
                const Icon = item.icon;
                const isAiAgent = item.id === "ai-agent";
                const isActive = isAiAgent ? isChatOpen : activeTab === item.id;
                
                const handleClick = () => {
                  if (isAiAgent) {
                    if (onToggleChat) {
                      onToggleChat();
                    } else {
                      setActiveTab(item.id);
                    }
                  } else {
                    setActiveTab(item.id);
                  }
                };

                return (
                  <div
                    key={item.id}
                    className={`nav-item ${isActive ? "active" : ""}`}
                    onClick={handleClick}
                  >
                    <Icon size={16} strokeWidth={isActive ? 2.2 : 1.8} />
                    <span>{item.label}</span>
                    {item.badge != null && item.badge > 0 && (
                      <span className="nav-badge">{item.badge}</span>
                    )}
                  </div>
                );
              })}
            </div>
          </div>
        ))}
      </div>

      {/* Bottom User Profile */}
      <div className="sidebar-user" onClick={() => setActiveTab("settings")}>
        <div className="user-avatar">{currentOperator.initials}</div>
        <div className="user-details">
          <span className="user-name">{currentOperator.name}</span>
          <span className="user-role">{currentOperator.role}</span>
        </div>
        <ChevronDown size={14} color="#64748b" />
      </div>
    </aside>
  );
}
