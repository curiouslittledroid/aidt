I want to explore creating an AI developer workflow to assist with developing the Mythical Forge application.                            
This workflow will wrap the Pi agent by invoking Pi on the command line with switches and flags.
We need to follow the workflow defined in docs/workflow.md, but we wont impliment every workflow step in one wrapper.
To start with lets break it up into the following distinct steps:
- task prompt generation and review
- implimentation and PR
- code review and github issue creation and approval
- github issue fixing

The workflow tooling will be in a folder called ./aidt, with wrapper scripts going in ./aidt/aidw

The workflow will leverage the prompts we have already created under .pi/prompts, but we may move them into a seperate directory under ./aidt/prompts.

Use python to write the scripts. The scripts will call the Pi agent using the command line, and pass in the model name and the prompt file to run.
You should also write any helper scripts to abstract common utilities and functions.

The workflow tools are seperate to the Mythical Forge app, and will be used to write the Mythical Forge app.
In essence I want to be able to select tasks from the roadmap to impliment, and have the Pi agent driven by scripts to follow the workflow.

I want to be able to define distinct agents for distinct tasks. These agents would be customised with their own agents.md file and/or their own system prompt (overriding Pi's prompt), and specifying speific LLM's.Therefore we need to define agent configs (yaml files stored in ./aidt/agent-configs) that define the model to use and what tools the model has access to.
