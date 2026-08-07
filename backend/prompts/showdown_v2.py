endpoint_selection_prompt = """
These are endpoints with their descriptions. Select the most appropriate endpoint for the given user query. If none of the endpoints are appropriate, respond with "None".
Endpoints wioth their descriptions:
{endpoints}

User query: {user_query}

Your response should be the name of the most appropriate endpoint or "None" if no endpoint is appropriate.
"""

router_to_endpoint_prompt = """
This is the user input: {user_input}
This is the endpoint selected by the LLM: {endpoint_selected}
These are the parameters needed for the selected endpoint: {params_needed}
These are the endpoints and descriptions with their output parameters: {endpoints}
Your task is to give the list of keys in a flow hit back to back which eventually leads to the selected endpoint. If the selected endpoint is not reachable, respond with "None".
Design the flow in this way that it needed least params and also which are avaiable or can be derived from the user input.
"""


provider_selection_prompt = """
This is the user input: {user_input}
Return the provider eg: Runpod, Novita etc.
"""


asking_question_prompt = """
This is the user input: {user_input}
This is how gpu struct looks like: 
 {
        "id": 21,
        "provider": "RunPod",
        "gpu_id": "NVIDIA RTX A5000",
        "gpu_name": "RTX A5000",
        "manufacturer": "Nvidia",
        "vram_gb": 24,
        "ram_gb": 25,
        "cpu": 9,
        "gpu_count": 1,
        "hourly_price": 0.16,
        "community_price": 0.16,
        "secure_price": 0.27,
        "spot_price": null,
        "availability": "unavailable",
        "deployable": 0,
        "reliability": null,
        "updated_at": "2026-08-04 06:14:09"
      },

Your task is to give the list of max 5 questions which can be asked to the user to get the most relevant gpu struct. The questions should be in a way that they are not repetitive and also they should be such that they can be answered by the user. If you think that no more questions are needed, respond with "None".
Also explain the reasoning behind each question in a separate line after the question. The reasoning should be in a way that it is understandable by the user and also it should be in a way that it helps the user to understand why the question is being asked.
"""