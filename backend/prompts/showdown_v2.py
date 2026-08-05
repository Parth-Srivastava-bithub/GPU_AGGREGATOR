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