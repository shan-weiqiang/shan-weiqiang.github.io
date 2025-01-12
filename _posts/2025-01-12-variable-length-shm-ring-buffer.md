---
layout: post
title:  "Variable-lengthed shared memory ring buffer"
date:   2025-01-12 09:22:46 +0800
tags: [c++]
---

A variable-length shard memory ring buffer that supports sharing variable length payloads data between processes. This is based on https://github.com/bo-yang/shm_ring_buffer, which only support POD fixed length data. The idea is illustrated in following diagram:


![alt text](/assets/images/var-length-ring-buffer.png)


Github: [shm_ring_buffer](https://github.com/shan-weiqiang/shm_ring_buffer)
