import os
from typing import List, Dict, Any, Optional
from google import genai
from google.genai import types
from pydantic import BaseModel

from app.core.config import get_settings

class ChatMessage(BaseModel):
    role: str
    content: str

class AgentService:
    def __init__(self):
        settings = get_settings()
        api_key = settings.gemini_api_key
        if not api_key:
            raise ValueError("CAUSALCUT_GEMINI_API_KEY is not set.")
        
        self.client = genai.Client(api_key=api_key)
        self.model_name = "gemini-3.1-flash-lite"
        
        # Define agent tools
        self.tools = [
            types.Tool(
                function_declarations=[
                    types.FunctionDeclaration(
                        name="get_factory_risk_status",
                        description="Get the real-time safety risk status of a specific factory or zone.",
                        parameters=types.Schema(
                            type=types.Type.OBJECT,
                            properties={
                                "factory_id": types.Schema(type=types.Type.STRING, description="The ID of the factory."),
                                "zone_id": types.Schema(type=types.Type.STRING, description="Optional. The specific zone ID.")
                            },
                            required=["factory_id"]
                        )
                    ),
                    types.FunctionDeclaration(
                        name="generate_compliance_report",
                        description="Generate and store a compliance or incident report based on a safety event.",
                        parameters=types.Schema(
                            type=types.Type.OBJECT,
                            properties={
                                "factory_id": types.Schema(type=types.Type.STRING, description="The ID of the factory."),
                                "title": types.Schema(type=types.Type.STRING, description="Title of the report."),
                                "content": types.Schema(type=types.Type.STRING, description="Detailed report content.")
                            },
                            required=["factory_id", "title", "content"]
                        )
                    )
                ]
            )
        ]
        
        self.system_instruction = (
            "You are CausalCut, an AI Safety Intelligence agent deployed in heavy industrial environments. "
            "Your goal is to monitor worker safety, provide proactive alerts, explain causal risk chains, "
            "and generate compliance reports. You have access to real-time factory data via tools. "
            "Always be concise, professional, and prioritize zero-harm operations. "
            "If an operator asks about an incident, use your tools to check the status or file a report."
        )

    def execute_tool(self, name: str, args: Dict[str, Any]) -> str:
        """Mock tool execution. In a real app, this would query Supabase/Engine."""
        if name == "get_factory_risk_status":
            zone = args.get("zone_id", "all zones")
            return f"Factory {args['factory_id']} ({zone}) is currently at MODERATE risk (0.45). 2 active permits, 1 minor gas anomaly detected."
        elif name == "generate_compliance_report":
            return f"Compliance report '{args['title']}' generated successfully and saved to DB for factory {args['factory_id']}."
        return f"Unknown tool {name}"

    async def chat(self, messages: List[ChatMessage]) -> str:
        # Convert internal message format to Gemini format
        formatted_contents = []
        for msg in messages:
            role = "user" if msg.role == "user" else "model"
            formatted_contents.append(
                types.Content(role=role, parts=[types.Part.from_text(msg.content)])
            )
            
        config = types.GenerateContentConfig(
            system_instruction=self.system_instruction,
            tools=self.tools,
            temperature=0.2,
        )

        try:
            # First pass
            response = self.client.models.generate_content(
                model=self.model_name,
                contents=formatted_contents,
                config=config,
            )
            
            # Handle tool calls if any
            if response.function_calls:
                for fc in response.function_calls:
                    tool_result = self.execute_tool(fc.name, fc.args)
                    
                    # Append function call and response to history
                    formatted_contents.append(response.candidates[0].content)
                    formatted_contents.append(
                        types.Content(
                            role="user",
                            parts=[types.Part.from_function_response(
                                name=fc.name,
                                response={"result": tool_result}
                            )]
                        )
                    )
                
                # Second pass with tool results
                response = self.client.models.generate_content(
                    model=self.model_name,
                    contents=formatted_contents,
                    config=config,
                )
                
            return response.text
            
        except Exception as e:
            return f"Agent Error: {str(e)}"
