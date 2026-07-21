# milton-for-antigravity

Milton is an AI based tool to collect, analyze and distill important information from the "mutterings" of coding LLMs. This version is being built for antigravity.

Milton is named after Milton Waddams from the movie "Office Space", whose mutterings get ignored, including when he promises to "burn down the place". 

## Background and Motivation

Coding LLMs such as Antigravity or Antigravity-CLI interact with the user in four ways:
1) They produce the generated artifact, often a diff or a document
2) They respond with a "final text" to a query.
3) They ask for further instructions or permissions
4) They show the "stream of thought" while "thinking".

Users typically pay attention to the first two because they are the intended outcome.
Requests for instructions or permissions are a blocker, but they are seen as a critical
and expected part of the process.

In contrast, "stream of thought" is secondary and ephemeral. Many IDEs will use it primarily to show progress - each new "thought" in the inner monologue would appear but may proceed to be erased when the next one arrives, often within seconds.  Or there will be a wall of text accumulating in the CLI until the final response is produced. If users are closely paying attention they may be observing this stream and perhaps cancelling if there is an obvious divergence. Users may also notice alarming sentences or notes. But this is down to luck.

While not as crucial as artifacts or requests, this secondary information could still be of importance. For instance, when a user is asked for permissions or to make a choice, the focus is often on the request ("does it look safe") and not on why it is being made, unless the agent makes that very clear. It is often difficult to recap "what has happened from the last prompt to this point" that has put us in this situation. For instance, what has the model been doing, and is it still on the right trajectory? What will this request accomplish?

The purpose of Milton is to help address this gap by collecting these "mutterings" of the AI, analyze them, and present the important information when the next turn appears.

## Approach

This version on of Milton is implemented as an API implemented via an agentic system, intended to be hosted locally or on a managed service with session management. Each coding session will correspond to an agentic coding system.

There will be four API methods or abilities for Milton:
1) ProcessTurn: This is the "upload stage". Milton will be given the user prompt, the full verbatim text of mutterings, and the current state/action. It will analyze and store them in the session memory. Milton may precompute and store in memory the respones to be used by the other methods below. 
2) ProcessFragment: This is the "upload" stage for a single item. Similar to ProcessTurn, but allow hooks to upload items as they pop up. Milton will queue the items for the fragment, or process them as they arrive, but be capable of preserving the chronological order. 
3) SummarizeMutterings: Milton will respond with a summary of all the mutterings, explain:
* What the AI did
* What it tried successfully and what it rejected
* Any important decisions or things the user should know about
* Any dangerous things
* Whether it needs additional information or permissions from the user.
4) ExplainUserRequest: Utilize the mutterings to just explain the latest information or permission request but without summarizing everything.

In most cases, Milton will respond to these based on only a single turn, but it may need to access earlier information in the session for details so we are saving it.

In addition to the API, we will have a plugin that works for Antigravity (or Google Internal Jetski) in either CLI or UI mode. There should be a way to have it in one of three modes: Off, Summarize Everything, and Only Explain Requests. 

Unless Milton is off, at the end of every turn the prompts, mutterings, responses, etc are sent. Or if we use hooks and don't have any other option, we will send each one separately. Then, when a turn complete and we have a response, we will present the summary/details OR we will present just the explanation for a choice. 
