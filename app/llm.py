import os
import anthropic
ANTHROPIC_API_KEY = os.environ["CLAUDE_API_KEY"]


MODEL = "claude-3-haiku-20240307"


SYSTEM_PROMPT = """You are an expert CI/CD assistant specializing in robotics projects using ROS 2, Docker, and Python.
Your task:
Analyze CI failure logs and provide a concise, actionable report with:
1. **Root cause** - specific technical reason (mention exact files, error types)
2. **Concrete fix** - exact commands or minimal code changes
3. **Prevention** - how to catch this locally before CI

Output format (strict markdown):
````markdown


### Root Cause
[Be specific: file paths, line numbers if available, exact error messages]

### Suggested Fix
```bash
# Exact commands to run locally
```
[If code changes needed, show minimal diff or explanation]

### Prevention
[Pre-commit hooks, local tests, or checks to add]
````

Pattern matching rules:
- **Pre-commit failures**: ALWAYS suggest `pre-commit run --all-files`, identify specific hooks that failed
- **Import errors**: Check package.xml (ROS 2) or requirements.txt (Python) for missing deps
- **ROS 2 runtime**: Check `ros2 node list`, topic discovery, parameter loading, DDS configuration
- **Docker issues**: Volume mounts, network mode (host vs bridge), GPU access, env vars
- **System tests**: Mention if rosbag artifacts (.mcap) are available in logs
- **Build errors**: CMakeLists.txt, missing build deps in package.xml
- **Linting errors**: Specific file paths and line numbers from error output

Style:
- Be concise but specific
- Don't repeat full log excerpts
- Focus on actionable next steps
- Use code blocks for commands
- Mention exact file paths when available in logs"""

def build_user_message(repo: str, build_number: int, failed_steps: list[dict]) -> str:
    logs_block = ""

    for step in failed_steps:
        logs_block += f"""
### Stage: {step['stage']} | Step: {step['step']}
````
{step['logs']}
````

"""

    return f"""**Build context:**
- Repository: `{repo}`
- Build number: `#{build_number}`
- Failed steps: {len(failed_steps)}

**Failure logs:**
{logs_block}

Analyze the failures above and provide your response following the specified format."""


async def ask_claude(repo: str, build_number: int, failed_steps: list[dict]) -> str:

    client = anthropic.AsyncAnthropic(api_key=ANTHROPIC_API_KEY)

    user_message = build_user_message(repo, build_number, failed_steps)

    message = await client.messages.create(
        model=MODEL,
        max_tokens=600,
        temperature=0.3,
        system=[
            {
                "type": "text",
                "text": SYSTEM_PROMPT,
                "cache_control": {"type": "ephemeral"}
            }
        ],
        messages=[
            {"role": "user", "content": user_message}
        ]
    )

    usage = message.usage
    cache_read = getattr(usage, 'cache_read_input_tokens', 0)
    cache_create = getattr(usage, 'cache_creation_input_tokens', 0)

    print(f"[LLM] Tokens - input: {usage.input_tokens}, "
          f"output: {usage.output_tokens}, "
          f"cache_read: {cache_read}, "
          f"cache_create: {cache_create}")

    if cache_read > 0:
        print(f"[LLM]  Saved {cache_read} cached tokens!")

    result = message.content[0].text

    return result