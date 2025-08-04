import os
import json
from ..validator.agent import AgentSchema
from ..utils.webhook import call_webhook_with_success, call_webhook_with_error
# from ..utils.temp_db import temp_data
from ..config.logger import Logger
from ..agent.base_agent import base_agent
logger = Logger()

class ExecuteController:
    """
    This class represents the controller for executing a task.
    """
    def execute(self, payload: AgentSchema) -> dict:
        """
        Executes the task using the provided payload.
        Args:
          payload (AgentSchema): The payload containing the data for the task.
        Returns:
          dict: The result of the task execution.
        Raises:
          Exception: If an error occurs during task execution.
        """
        try:
            logger.info('ExecuteController.execute() method called')

            # Get payload data
            payload = payload.dict()
            print(f"payload -> {payload}")

            # Prepare inputs
            inputs = {
                'id': payload.get('id'), 
                'webhookUrl': payload.get('webhookUrl')
            }

            # Extract all inputs from the payload
            for item in payload.get('inputs', []):
                inputs[item.get('name')] = item.get('data')
                
            responses = base_agent(inputs)
            
            # """ 
            #     GENERAL AGENT TEMPLATE
                
            #     - This is the general agent template that we should use in this execute function below. 
            #     - If you'd like to proceed in this format, please either delete the rest of agent templates or comment them in.
            # """

            # Call webhook with success
            call_webhook_with_success(payload.get('id'),{
                "status": 'completed',
                "data": {
                    "info": "Task successfully completed!",
                    "output": responses
                }
            })

            logger.info('Function execute: Execution complete', responses)
            return {"result": responses}
            
            
        except Exception as e:
            logger.error('Getting Error in ExecuteController.execute:', e)
            raise call_webhook_with_error(payload.get('id'),str(e), 500)