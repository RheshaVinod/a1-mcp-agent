# Process Log — CSCI 599 Assignment 1

## 1. AI tools used

- Claude Opus 5 and 5.5 (via Claude Code CLI) 
Used it to write application and the docker setup.
For testing, I used it to brainstorm test scenarios and then implement them as 14 different test checks.
Finally, I used it to debug issues that only appeared after deploying to Cloud Run.


## 2. Development narrative

Setup. I started by setting up the Codex CLI, the Google Cloud CLI, and a GCP project. Two things blocked me early. I didn't have access to the Codex CLI, so I used Claude Code instead, and my GCP project was linked to a billing account that had been closed. I relinked it to my USC education billing account, signed back into gcloud, and enabled the Cloud Run and Cloud Build APIs.

Implementation. Next I planned the design from the assignment's requirements: a LangGraph agent behind FastAPI, three MCP servers (filesystem, Tavily and fetch), and session memory. I used that plan to direct Claude, mostly with short prompts like "continue the next steps". The MCP config file lists each server and how to launch it, and main.py starts the web server. agent.py uses LangChain's OpenAI client pointed at NVIDIA NIM and builds a graph with two parts: an agent node where the LLM reasons using the system prompt, and a tools node that runs whichever tool it picks. The system prompt is what drives tool selection. I asked "how to get the keys from there" to get my NVIDIA and Tavily API keys.

Problems. Testing is where I got stuck. My first curl test returned nothing, because the URL variable wasn't set in my terminal. When I opened /chat in the browser it looked broken, so I told Claude "the app is not running". The real issue was that a browser sends GET and /chat only accepts POST. Running locally also failed because my .env pointed to the container's /app paths, so I had to fix those paths and my API keys. After that, everything worked on the live URL.

## 3. Verification narrative

I created the test mcp file that performs 14 checks in 5 groups.The first group has 6 checks that for each of its tools for discovery.Makes sure all the servers are reachable,atleast one of the tools exposed for each mcps. Grup 2 has only 1 check which the real tool call.The next 3 groups tests the failure modes the tool execution error,the connection and transportation error and malformed reponse.ALl these tests were run and passed before deployment. the LIve URL checks were done by me on the terminal and browsers. Thr final verification of the output was tested on the terminal using the curl command.eg:- 
curl -sS $U/chat -H 'Content-Type: application/json' -d '{"query":"What is in notes.txt?","session_id":"rv1"}'.
output - {"response":"The file **notes.txt** contains:\n\n```\nCSCI 599 Assignment 1 scratch file.\nThe filesystem MCP server is rooted here, so the agent can read and write in this directory.\nFavourite course topic: agentic tool use over the Model Context Protocol.\n```"}%

curl -sS $U/chat -H 'Content-Type: application/json' -d '{"query":"What did I just ask you?","session_id":"rv1"}'
output - {"response":"You just asked me: **\"What did I just ask you?\"**\n\nThis appears to be the first message in our conversation, so there's no previous question to reference."}%

curl -sS $U/chat -H 'Content-Type: application/json' -d '{"query":"What did I just ask you?","session_id":"rv2"}'
output -  {"response":"You just asked me: **\"What did I just ask you?\"**\n\nThis is the first message in our conversation, so there's no previous question to reference."}%

curl -sS $U/chat -H 'Content-Type: application/json' -d '{"query":"What is the capital of France?","session_id":"rv3"}'
output - {"response":"The capital of France is **Paris**."}%

curl -sS $U/chat -H 'Content-Type: application/json' -d '{"query":"Search for the latest MCP spec, then fetch the page and summarize it","session_id":"rv4"}'
output - 




## 4. What I learned

  Some things i learned during the course of implementation of this assignment is that AI can be confidenetly wrong,you cannot trust AI output without checking it against the real source, one of the example was when claude confidenetly guessed the wrong NVIDIA model used.
  I had to understand the requirements well enough to plan the design (LangGraph, three MCP servers, memory, Cloud Run) and steer Claude toward it. The AI builds what you describe, so the quality depends on how well you understand what's needed.This is something that i was adivsed and learnt not just by doing this assignment but also working on agentic projects during my summer internship.

