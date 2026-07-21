#!/usr/bin/env python3
"""Interactive Mock Agent Runner to demonstrate Milton Plugin exfiltration and intervention."""

import sys
import time
from pathlib import Path

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from plugins.antigravity.plugin import MiltonAntigravityPlugin, MiltonMode


def run_mock_agent_turn(mode: MiltonMode):
    print(f"\n" + "#"*70)
    print(f"🚀 RUNNING MOCK AGENT TURN WITH MILTON PLUGIN MODE: [{mode.value}]")
    print("#"*70 + "\n")

    plugin = MiltonAntigravityPlugin(mode=mode)
    plugin.on_session_start(session_id="session-12345", workspace_paths=["/workspace/my_project"])

    # 1. User Prompt
    user_prompt = "Find all configuration files and run the test suite."
    print(f"👤 USER PROMPT: \"{user_prompt}\"\n")
    plugin.on_user_prompt(user_prompt)

    # 2. Agent Muttering / Inner Monologue 1
    muttering_1 = "I need to locate the config files in the workspace. Let me check the directory contents first."
    print(f"💭 [Agent Monologue 1]: \"{muttering_1}\"")
    plugin.on_muttering(muttering_1)
    time.sleep(0.3)

    # 3. Safe Tool Call (read_file)
    print("\n🛠️ [Agent Action]: Executing tool 'list_dir'...")
    intervention = plugin.on_pre_tool_call(tool_name="list_dir", tool_args={"DirectoryPath": "/workspace/my_project"}, step_idx=1)
    if intervention:
        print(f"   👉 INTERVENTION TRIGGERED: {intervention['reason']}")
    plugin.on_post_tool_call(tool_name="list_dir", tool_output="config.yaml, main.py, tests/")
    time.sleep(0.3)

    # 4. Agent Muttering 2
    muttering_2 = "Found config.yaml. Now I need to run bash command pytest to execute all tests."
    print(f"\n💭 [Agent Monologue 2]: \"{muttering_2}\"")
    plugin.on_muttering(muttering_2)
    time.sleep(0.3)

    # 5. Sensitive Tool Call requiring permission (run_command)
    print("\n🛠️ [Agent Action]: Attempting sensitive tool 'run_command'...")
    intervention = plugin.on_pre_tool_call(tool_name="run_command", tool_args={"CommandLine": "pytest tests/"}, step_idx=2)
    if intervention:
        print(f"\n🚨 [HOOK INTERVENTION ACTIVE] Permission Prompt Modified:")
        print(f"   Reason shown to user: {intervention['reason']}\n")

    plugin.on_post_tool_call(tool_name="run_command", tool_output="3 passed in 0.42s")
    time.sleep(0.3)

    # 6. Turn Complete
    final_response = "All configuration files were inspected and all 3 tests passed successfully."
    print(f"\n🤖 AGENT FINAL RESPONSE: \"{final_response}\"")

    summary_output = plugin.on_turn_complete(final_response)
    if summary_output:
        print(summary_output)


if __name__ == "__main__":
    print("Testing Milton Plugin Modes...")
    
    # Run test in SUMMARIZE_EVERYTHING mode
    run_mock_agent_turn(MiltonMode.SUMMARIZE_EVERYTHING)
    
    print("\n" + "-"*70 + "\n")
    
    # Run test in ONLY_EXPLAIN_REQUESTS mode
    run_mock_agent_turn(MiltonMode.ONLY_EXPLAIN_REQUESTS)
