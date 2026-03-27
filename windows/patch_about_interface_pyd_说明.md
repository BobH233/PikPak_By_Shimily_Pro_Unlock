# `patch_about_interface_pyd.py` 说明

本文档说明如何使用 `patch_about_interface_pyd.py` 对 `about_interface.pyd` 打补丁，使核心校验函数始终返回 `True`。

全文只使用文件名、相对路径、函数地址和机器码，不包含任何本机用户名或绝对路径信息。

## 目标

根据逆向分析，Windows 版 `about_interface.pyd` 中真正负责拍板校验结果的核心函数是：

- `sub_180001CA0` at `0x180001CA0`

外层包装入口是：

- `sub_180001990` at `0x180001990`

成功和失败出口分别是：

- 成功返回 `True`：`0x180002389`
- 失败返回 `False`：`0x1800025C3`

这次补丁没有去改外层参数解析，也没有只改某个条件跳转，而是直接把核心函数 `sub_180001CA0` 的入口替换成“立即返回 `Py_True`”。

## 补丁思路

原始函数入口从 `0x180001CA0` 开始，前 11 个字节是：

```text
4c 8b dc 55 56 41 56 49 8d 6b a1
```

对应的是函数序言：

```asm
mov     r11, rsp
push    rbp
push    rsi
push    r14
lea     rbp, [r11-5Fh]
```

脚本会把这 11 个字节改成：

```text
48 8b 05 01 27 02 00 48 ff 00 c3
```

对应汇编语义是：

```asm
mov     rax, cs:_Py_TrueStruct
inc     qword ptr [rax]
ret
```

效果是：

1. 进入 `sub_180001CA0` 后，不再执行原本复杂的验证流程。
2. 直接取到 `_Py_TrueStruct`。
3. 手动增加一次引用计数。
4. 立即返回。

这样返回值仍然是合法的 Python `True` 对象，而不是一个裸常量或错误的寄存器值。

## 为什么选函数入口补丁

这个方案的优点是：

- 改动点单一，只改 11 个字节。
- 不依赖中间控制流是否发生变化。
- 不需要关心 `rsa.verify(...)` 的具体参数构造过程。
- 不会走到失败出口 `0x1800025C3`。

相比之下，直接改中间条件跳转有一个风险：如果某些错误路径返回的是空指针，强行跳到成功分支可能触发后续 `DECREF` 或空指针访问。入口早返回更稳。

## 脚本做了什么

`patch_about_interface_pyd.py` 会按下面的步骤执行：

1. 解析 PE32+ 头。
2. 读取 section table。
3. 将 `VA 0x180001CA0` 映射成文件偏移。
4. 校验该位置当前字节是否仍是预期的函数序言。
5. 动态生成 `mov rax, [rip+disp32]; inc qword ptr [rax]; ret`。
6. 写出 patched 文件。

其中几个关键常量是：

```python
TARGET_FUNCTION_VA = 0x180001CA0
PY_TRUE_IAT_VA = 0x1800243A8
EXPECTED_PROLOGUE = bytes.fromhex("4C 8B DC 55 56 41 56 49 8D 6B A1")
```

`PY_TRUE_IAT_VA` 指向导入表中的 `_Py_TrueStruct` 指针槽位，因此脚本不是写死某个运行时地址，而是使用当前模块内部已经存在的导入地址。

## 当前样本上的定位结果

对当前这份 `about_interface.pyd`，脚本实际计算出的信息是：

- image base: `0x180000000`
- patch VA: `0x180001CA0`
- patch file offset: `0x10a0`

也就是说，文件偏移 `0x10a0` 开始的 11 个字节会被替换。

## 使用方法

生成 patched 文件：

```bash
python3 patch_about_interface_pyd.py about_interface.pyd -o about_interface.pyd.patched -f
```

如果不写 `-o`，默认输出文件名是：

```text
about_interface.pyd.patched
```

## 运行成功后的典型输出

脚本会输出类似下面的信息：

```text
image base:       0x180000000
patch VA:         0x180001ca0
patch file offset: 0x10a0
original bytes:   4c 8b dc 55 56 41 56 49 8d 6b a1
patched bytes:    48 8b 05 01 27 02 00 48 ff 00 c3
patched file written to: about_interface.pyd.patched
```

## 校验与保护

脚本在写补丁前会做两层保护：

1. 如果目标位置已经是补丁字节，直接报错，避免重复 patch。
2. 如果目标位置不是预期原始字节，也会报错，避免误补到别的版本或错误文件。

这意味着它不是“盲写偏移”，而是“校验后再写”。

## 补丁边界

这个补丁生效的前提是：

- 外层仍然会正常调用 `sub_180001CA0`
- 调用方期望收到的是 Python 布尔对象

它不会改变：

- `sub_180001990` 的参数个数检查
- 参数类型错误时的报错路径
- 模块导入和初始化逻辑

所以更准确地说，补丁效果是：

- 只要调用已经进入核心校验函数，就会直接返回 `True`

而不是：

- 无条件绕过所有外层调用约束

## 文件

相关文件如下：

- `patch_about_interface_pyd.py`
- `about_interface.pyd`
- `about_interface.pyd.patched`

