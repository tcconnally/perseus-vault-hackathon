# Use the official AWS Lambda base image for Python 3.11
FROM public.ecr.aws/lambda/python:3.11

# Set the working directory in the container
WORKDIR ${LAMBDA_TASK_ROOT}

# Copy the requirements file into the container
COPY requirements.txt .

# Install dependencies
# Using --no-cache-dir reduces the image size
RUN pip install -r requirements.txt --no-cache-dir

# Copy the agent code and schema script into the container
COPY agent.py .
COPY bedrock_agent.py .
COPY db_schema.py .

# TODO: The ccloud CLI needs to be installed for the health check.
# This requires downloading and installing the binary.
# The URL is architecture-specific.
# Example for linux-amd64:
RUN curl -sSL https://binaries.cockroachdb.com/ccloud-v1.0.3.linux-amd64.tar.gz | tar -xzv
RUN mv ccloud /usr/local/bin/

# Set the CMD to your handler. 
# This tells Lambda where to find your handler function.
# The format is <filename>.<handler_function_name>
# We will create a `handler.py` file to wrap the agent logic for Lambda.
# For now, this is a placeholder.
CMD [ "handler.handler" ]
