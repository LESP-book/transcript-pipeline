# WSL2 Debian Setup Docs Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 在 README 中补充从零开始的 WSL2 + Debian + NVIDIA 3060Ti 部署清单，帮助用户在 GPU 机器上运行本项目。

**Architecture:** 仅修改文档，不改代码。README 新增一节，按 Windows 宿主机准备、Debian 基础环境、项目安装、CUDA/cuDNN 运行库、验证步骤、实际运行命令的顺序组织，引用官方安装约束并保持命令可复制。

**Tech Stack:** Markdown, GitHub README

---

### Task 1: 核对部署要点

**Files:**
- Modify: `README.md`

**Step 1: Collect official requirements**

核对以下要点后再写文档：
- Windows 侧 WSL 更新与 NVIDIA 驱动
- WSL 内不要安装 Linux NVIDIA 驱动
- faster-whisper 在 GPU 上的 CUDA/cuDNN 运行库要求

### Task 2: 更新 README

**Files:**
- Modify: `README.md`

**Step 1: Add deployment checklist**

新增一节，包含：
- Windows 宿主机准备
- Debian 基础依赖安装
- 项目 clone 与 `.venv`
- CUDA/cuDNN Python wheel 运行库
- `LD_LIBRARY_PATH` 设置
- `nvidia-smi` / `pytest` / GPU 冒烟测试
- `wsl2_gpu` / `wsl2_gpu_max_accuracy` 运行命令

### Task 3: 验证

**Files:**
- Reference: `docs/REVIEW_CHECKLIST.md`

**Step 1: Run tests**

Run: `.venv/bin/python -m pytest`

Expected: PASS
