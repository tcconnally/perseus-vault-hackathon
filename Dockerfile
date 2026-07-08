# AWS Lambda container image for the Perseus Vault agent.
FROM public.ecr.aws/lambda/python:3.11

WORKDIR ${LAMBDA_TASK_ROOT}

COPY requirements.txt .
RUN pip install -r requirements.txt --no-cache-dir

# Agent + memory engine + Lambda entrypoint.
COPY vault_core.py agent.py bedrock_agent.py db_schema.py decay.py lambda_handler.py ./

# Lambda invokes this entrypoint (<module>.<function>).
CMD [ "lambda_handler.handler" ]
