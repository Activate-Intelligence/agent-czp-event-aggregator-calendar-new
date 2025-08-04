import os
import json
from ..utils.error_handling import error_handler
from ..config.logger import Logger

logger = Logger()


class DiscoverController:
    """
    Controller class for handling discovery related operations.
    """

    @classmethod
    def documentation(cls):
        """
        Retrieves the API documentation from the agent.json file.

        Returns:
            dict: The API documentation as a dictionary.

        Raises:
            Exception: If there is an error while retrieving the documentation.
        """
        try:
            logger.info("DiscoverController.documentation() method called")
            doc = {}
            current_directory = os.path.dirname(__file__)
            file_path = os.path.normpath(
                os.path.join(current_directory, '../config/agent.json'))

            with open(file_path, "r") as json_file:
                doc = json.load(json_file)

            return doc
        except Exception as e:
            logger.error(
                'Getting Error in DiscoverController.documentation:', e)
            raise error_handler(e, 500)
