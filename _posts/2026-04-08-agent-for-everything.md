---
layout: post
title:  "Agent For Everything"
date:   2026-04-08 8:22:46 +0800
tags: [systems]
---

* toc
{:toc}

# Prior reading

The article [openclaw-system-architecture-overview](https://ppaolo.substack.com/p/openclaw-system-architecture-overview) explains in detail how OpenClaw works. My takeaways:

- LLMs let computers *interpret* human natural language.
- Agents (OpenClaw, Cursor, Claude Code, and similar) give LLMs a runtime so they can operate the computer (for now, still mostly software on the machine).
- What comes next? Driving peripheral hardware and mechanical systems is only a matter of time.

If we treat software, hardware, and machines as tools, then LLMs plus agents mean people can wield those tools with **natural language** instead of doing every step by hand. With a “brain,” tools, and instructions in human language—how is that fundamentally different from an individual human?

# A small experiment: Agent-Smith

Repository: https://github.com/shan-weiqiang/agent-smith?tab=readme-ov-file

I built a small agent that takes natural-language instructions and can:

- Accept instructions to define, change, or delete Protobuf message types  
  (instructions can be plain language or existing artifacts such as JSON, C++, or `.proto` files.)
- Accept instructions to query or search all Protobuf message types
- Accept instructions to compile them into Python or C++ generated code
- Accept instructions to compile C++ sources into a shared library

All of this can be driven from the command line with natural-language interaction:

![alt text](/assets/output.gif)

# Tools in the form of Agent

**Agents let people use tools through natural language. So all tools should be provided in the form of an Agent**

![alt text](/assets/images/agent_arch.png)

