import re

with open('dashboard/src/App.jsx', 'r', encoding='utf-8') as f:
    content = f.read()

# 1. Add import
if 'ScenarioHistoryView' not in content:
    content = content.replace('import AiAgentView from "./components/views/AiAgentView";', 
                              'import AiAgentView from "./components/views/AiAgentView";\nimport ScenarioHistoryView from "./components/views/ScenarioHistoryView";')

# 2. Add Database icon import
if 'Database' not in content:
    content = content.replace('import { MessageSquare }', 'import { MessageSquare, Database }')

# 3. Add sidebar item
nav_item = '''          <li className={activeTab === "history" ? "active" : ""} onClick={() => setActiveTab("history")}>
            <Database size={18} />
            <span>Scenario History (DB)</span>
          </li>'''
if 'Scenario History' not in content:
    content = content.replace('<span>Simulation & Scenarios</span>\n          </li>', 
                              '<span>Simulation & Scenarios</span>\n          </li>\n' + nav_item)

# 4. Add to switch statement
render_case = '''      case "history":
        return <ScenarioHistoryView onNavigate={setActiveTab} />;'''
if 'case "history":' not in content:
    content = content.replace('case "simulation":', render_case + '\n      case "simulation":')

with open('dashboard/src/App.jsx', 'w', encoding='utf-8') as f:
    f.write(content)

print('App.jsx patched successfully')
