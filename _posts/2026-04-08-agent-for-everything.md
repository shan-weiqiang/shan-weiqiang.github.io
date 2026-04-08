---
layout: post
title:  "Agent For Everything"
date:   2026-04-08 9:22:46 +0800
tags: [systems]
---

* toc
{:toc}

**Agent 可以让人用自然语言使用工具**。

# 参考文章

[openclaw-system-architecture-overview](https://ppaolo.substack.com/p/openclaw-system-architecture-overview) 这篇文章详细解释了openclaw的工作原理。我的思考是：

- LLM的出现让计算机能够*理解*人类自然语言
- Agent（openclaw/cursor/claude code）为LLM提供了运行时环境，使其能够操作计算机（目前为止还仅限于计算机软件）
- 未来呢？操作外围硬件/机械装置是早晚的事情

如果把计算机软件/硬件/机械装置看成是各种工具，那LLM和Agent的出现让人可以使用**自然语言**使用工具，而不是亲自操作。有了大脑，又有了工具，又能接受人类自然语言的指令，那这和人类个体有什么区别呢？

# 一个简单的试验：Agent-Smith

仓库地址：https://github.com/shan-weiqiang/agent-smith?tab=readme-ov-file

编写了一个简单的Agent，它可以接受人类的自然语言指令，完成以下工作：

- 接收指令，定义/更改/删除protobuf类型的消息结构体
    - 指令可以是语言描述，也可以是现有的文件，例如json/c++/现存的proto等
- 接收指令查询/检索所有protobuf类型的消息
- 接收指令编译成对应的python/c++类型文件
- 接收指令将c++源码编译成动态库

以上工作全部可以通过命令行使用自然语言交互完成：
![alt text](../assets/output.gif)

