#!/usr/bin/env python3
"""
AI Code Review Script
调用 LLM API 对 PR diff 进行代码审查
"""

import os

import httpx

SYSTEM_PROMPT = """你是一个资深的代码审查专家。请审查以下 Pull Request 的代码变更。

你需要关注以下方面：
1. **潜在的 Bug 和边缘情况** - 未处理的异常、空值检查、边界条件等
2. **安全漏洞** - SQL注入、XSS、敏感信息泄露、不安全的依赖等
3. **性能问题** - 不必要的循环、内存泄漏、N+1查询等
4. **代码质量** - 可读性、命名规范、重复代码、过于复杂的逻辑
5. **最佳实践** - 是否遵循该语言/框架的最佳实践

**请忽略以下文件的变更，不要对它们进行审查：**
- requirements.txt、requirements*.txt 等依赖声明文件
- 这些文件只是依赖版本声明，不需要代码审查

请用中文回复，格式如下：
- 如果发现问题，列出具体的问题和建议，引用具体的代码行
- 如果代码质量良好，简单说明即可
- 不要过度挑剔，只关注真正重要的问题

回复格式：
### 🤖 AI Code Review

**审查的提交:** `{commit_sha}`

#### 发现的问题

（如果有问题，按严重程度列出）

#### 总结

（简短总结代码质量）

---
<details>
<summary>ℹ️ 关于此审查</summary>

此审查由 AI 自动生成，仅供参考。如有误报请忽略。

</details>
"""


def getDiffContent() -> str:
    """读取 PR diff 内容"""
    diffFile = os.environ.get("diff_file", "pr_diff.txt")
    if os.path.exists(diffFile):
        with open(diffFile, encoding="utf-8", errors="ignore") as f:
            return f.read()

    # 备用：直接读取
    if os.path.exists("pr_diff.txt"):
        with open("pr_diff.txt", encoding="utf-8", errors="ignore") as f:
            return f.read()

    return ""


def truncateDiff(diff: str, maxChars: int = 60000) -> str:
    """截断过长的 diff，避免超出 token 限制"""
    if len(diff) <= maxChars:
        return diff

    return diff[:maxChars] + "\n\n... (diff 过长，已截断)"


def callChatApi(
    apiKey: str,
    baseUrl: str,
    model: str,
    systemPrompt: str,
    userMessage: str,
) -> str:
    """
    调用 OpenAI Chat Completions API

    Args:
        apiKey: API 密钥
        baseUrl: API 基础 URL (如 https://api.openai.com/v1)
        model: 模型名称
        systemPrompt: 系统提示
        userMessage: 用户消息

    Returns:
        模型响应内容
    """
    # 拼接完整 URL: baseUrl + /chat/completions
    url = baseUrl.rstrip("/") + "/chat/completions"

    headers = {
        "Authorization": f"Bearer {apiKey}",
        "Content-Type": "application/json",
    }

    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": systemPrompt},
            {"role": "user", "content": userMessage},
        ],
        "temperature": 0.3,
        "max_tokens": 2000,
    }

    with httpx.Client(timeout=120) as client:
        response = client.post(url, headers=headers, json=payload)
        if response.status_code != 200:
            raise Exception(f"HTTP {response.status_code}: {response.text}")
        data = response.json()

    # 校验响应结构
    choices = data.get("choices", [])
    if not choices:
        raise Exception(f"API 响应缺少 choices 字段: {data}")
    return choices[0].get("message", {}).get("content", "")


def callMessagesApi(
    apiKey: str,
    baseUrl: str,
    model: str,
    systemPrompt: str,
    userMessage: str,
) -> str:
    """
    调用 Anthropic Messages API

    Args:
        apiKey: API 密钥
        baseUrl: API 基础 URL (如 https://api.anthropic.com/v1)
        model: 模型名称
        systemPrompt: 系统提示
        userMessage: 用户消息

    Returns:
        模型响应内容
    """
    # 拼接完整 URL: baseUrl + /messages
    url = baseUrl.rstrip("/") + "/messages"

    headers = {
        "x-api-key": apiKey,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }

    payload = {
        "model": model,
        "max_tokens": 2000,
        "system": systemPrompt,
        "messages": [{"role": "user", "content": userMessage}],
    }

    with httpx.Client(timeout=120) as client:
        response = client.post(url, headers=headers, json=payload)
        if response.status_code != 200:
            raise Exception(f"HTTP {response.status_code}: {response.text}")
        data = response.json()

    # 校验响应结构
    content = data.get("content", [])
    if not content:
        raise Exception(f"API 响应缺少 content 字段: {data}")
    return content[0].get("text", "")


def callResponseApi(
    apiKey: str,
    baseUrl: str,
    model: str,
    systemPrompt: str,
    userMessage: str,
) -> str:
    """
    调用 OpenAI Responses API

    Args:
        apiKey: API 密钥
        baseUrl: API 基础 URL (如 https://api.openai.com/v1)
        model: 模型名称
        systemPrompt: 系统提示
        userMessage: 用户消息

    Returns:
        模型响应内容
    """
    # 拼接完整 URL: baseUrl + /responses
    url = baseUrl.rstrip("/") + "/responses"

    headers = {
        "Authorization": f"Bearer {apiKey}",
        "Content-Type": "application/json",
    }

    payload = {
        "model": model,
        "instructions": systemPrompt,
        "input": userMessage,
    }

    with httpx.Client(timeout=120) as client:
        response = client.post(url, headers=headers, json=payload)
        if response.status_code != 200:
            raise Exception(f"HTTP {response.status_code}: {response.text}")
        data = response.json()

    # Responses API 返回格式: output_text 或 output 数组
    if "output_text" in data:
        return data["output_text"]

    # 解析 output 数组结构
    output = data.get("output", [])
    if output and isinstance(output, list):
        for item in output:
            if item.get("type") == "message":
                content = item.get("content", [])
                # 遍历 content 找到 output_text 类型
                for block in content:
                    if block.get("type") == "output_text":
                        return block.get("text", "")
    raise Exception(f"无法解析 Responses API 响应: {data}")


VALID_API_TYPES = {"chat", "messages", "response"}


def callLlmApi(
    apiKey: str,
    baseUrl: str,
    model: str,
    systemPrompt: str,
    userMessage: str,
    apiType: str,
) -> str:
    """
    统一调用 LLM API

    Args:
        apiKey: API 密钥
        baseUrl: API 基础 URL (如 https://api.openai.com/v1)
        model: 模型名称
        systemPrompt: 系统提示
        userMessage: 用户消息
        apiType: API 类型 ('chat', 'messages', 'response')

    Returns:
        模型响应内容
    """
    if apiType not in VALID_API_TYPES:
        raise ValueError(f"无效的 API 类型: '{apiType}'，支持的类型: {VALID_API_TYPES}")

    print(f"Using API type: {apiType}")

    if apiType == "messages":
        return callMessagesApi(apiKey, baseUrl, model, systemPrompt, userMessage)
    elif apiType == "response":
        return callResponseApi(apiKey, baseUrl, model, systemPrompt, userMessage)
    else:
        return callChatApi(apiKey, baseUrl, model, systemPrompt, userMessage)


def main():
    apiKey = os.environ.get("LLM_API_KEY")
    if not apiKey:
        print("Error: LLM_API_KEY not set")
        return

    baseUrl = os.environ.get("LLM_BASE_URL")  # 必需，如 https://api.openai.com/v1
    if not baseUrl:
        print("Error: LLM_BASE_URL not set")
        return

    model = os.environ.get("LLM_MODEL")
    if not model:
        print("Error: LLM_MODEL not set")
        return

    apiType = os.environ.get("LLM_API_TYPE", "chat")  # chat, messages, response

    prTitle = os.environ.get("PR_TITLE", "")
    prBody = os.environ.get("PR_BODY", "")

    # 获取 commit SHA
    commitSha = os.environ.get("GITHUB_SHA", "unknown")[:10]

    diffContent = getDiffContent()
    if not diffContent:
        print("No diff content found, skipping review")
        return

    diffContent = truncateDiff(diffContent)

    # 构造用户消息
    userMessage = f"""## Pull Request 信息

**标题:** {prTitle}

**描述:**
{prBody or "无描述"}

## 代码变更 (diff)

```diff
{diffContent}
```

请审查以上代码变更。"""

    try:
        systemPrompt = SYSTEM_PROMPT.format(commit_sha=commitSha)
        reviewContent = callLlmApi(
            apiKey=apiKey,
            baseUrl=baseUrl,
            model=model,
            systemPrompt=systemPrompt,
            userMessage=userMessage,
            apiType=apiType,
        )

        # 写入结果文件
        with open("review_result.md", "w", encoding="utf-8") as f:
            f.write(reviewContent)

        print("Review completed successfully!")
        print(reviewContent)

    except Exception as e:
        print(f"Error calling LLM API: {e}")


if __name__ == "__main__":
    main()
