# DataSet

## 环境准备

建议使用 Conda 创建独立环境：

```bash
conda create -n dataset python=3.11 -y
conda activate dataset
```

安装 Python 依赖：

```bash
pip install -r requirements.txt
```

## 编译器依赖

本项目中的编译与校验脚本默认使用 `g++`，当前代码不依赖 `libclang`。

Ubuntu / Debian:

```bash
sudo apt update
sudo apt install -y g++
```

如果你希望一次装全基础构建工具，也可以用：

```bash
sudo apt update
sudo apt install -y build-essential
```

CentOS / Rocky / AlmaLinux:

```bash
sudo yum install -y gcc-c++
```

如果要改用 `clang++`，可以在运行脚本时手动传入 `--compiler clang++`。
