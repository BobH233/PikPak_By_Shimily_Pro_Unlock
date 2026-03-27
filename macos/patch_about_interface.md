# `patch_about_interface.py` 工作原理说明

本文档说明如何对 `about_interface.so` 打补丁，使 `MyEncrypt.checkLicense(...)` 无论传入什么 `secret` / `key` / `license`，最终都走到返回 `True` 的路径。

## 1. 目标与总体思路

目标函数是：

- `___pyx_pw_15about_interface_9MyEncrypt_3checkLicense`

根据前面的逆向结果，这个函数里真正决定校验成败的核心点是 `rsa.verify(...)` 那次调用。原始逻辑中：

- 在 `0xddb3` 调用 `___Pyx_PyObject_FastCallDict`
- 在 `0xddb8` 取返回值到 `r15`
- 若返回值非空且没有异常，则继续清理并进入成功路径
- 在 `0xde14` 开始构造并返回 `Py_True`

脚本没有粗暴地把函数入口改成直接 `ret`，而是选择了一个更稳的补丁方式：

- 不再真正调用 `rsa.verify(...)`
- 直接把 `Py_True` 对象指针装入 `r15`
- 让后面的清理逻辑和成功返回路径照常执行

这样做的好处是：

- 不会破坏函数栈平衡
- 不会跳过后面已有的引用计数清理逻辑
- 不依赖手工改写整段函数控制流

## 2. 为什么不用固定偏移

最初已经确认当前样本里的补丁点文件偏移是：

- `0xDDB3`

但如果不同版本重新编译，哪怕函数还是同一个，偏移也很可能变化。因此脚本没有写死 `0xDDB3`，而是改为：

1. 先按符号名定位目标函数
2. 再只在该函数内部搜索特征码
3. 找到补丁点后动态生成补丁字节

这样可以兼容同系列不同版本，只要：

- 符号表还保留
- `checkLicense` 这个包装函数名字没变
- 函数内部的关键局部指令模式没有被彻底改写

## 3. 符号定位部分

脚本会先手工解析 Mach-O 头和加载命令，读取：

- `LC_SEGMENT_64`
- `LC_SYMTAB`

然后从符号表中查找目标符号：

```text
___pyx_pw_15about_interface_9MyEncrypt_3checkLicense
```

对应代码常量是：

```python
TARGET_SYMBOL = "___pyx_pw_15about_interface_9MyEncrypt_3checkLicense"
```

找到该符号后，脚本会：

- 读取它的 `n_value` 作为函数起始虚拟地址
- 在 `__TEXT` 段中估算函数大小
- 将函数虚拟地址映射到文件偏移
- 截取出该函数对应的二进制字节区间

这里函数大小不是从反汇编器拿的，而是通过“下一个位于 `__TEXT` 段中的符号地址减去当前符号地址”来估算的。

## 4. 函数内特征搜索

### 4.1 搜索真正的补丁点

脚本不会直接扫全文件，而是只在 `checkLicense` 这个函数的字节范围内搜索下面这段通配特征：

```python
CALLSITE_PATTERN = (
    "E8 ?? ?? ?? ?? 49 89 C7 48 89 85 50 FF FF FF 4D 85 E4 74 0A"
)
```

这段特征对应的汇编语义大致是：

```asm
call    ___Pyx_PyObject_FastCallDict
mov     r15, rax
mov     [rbp-0xb0], rax
test    r12, r12
jz      short ...
```

其中：

- `E8 ?? ?? ?? ??` 是 `call rel32`
- `??` 表示通配符，因为不同版本里相对偏移可能变化

这段模式的意义是：

- 前面刚完成参数准备
- 中间本来要真正调用 `rsa.verify(...)`
- 后面马上接收返回值并进入统一收尾逻辑

也就是说，这就是最合适的“替换调用结果而不破坏整体流程”的位置。

### 4.2 搜索 `Py_True` 的现成加载指令

脚本还会在同一个函数里搜索：

```python
PY_TRUE_PATTERN = "4C 8B 35 ?? ?? ?? ?? 49 FF 06"
```

它对应的是成功返回路径开头的指令：

```asm
mov     r14, cs:__Py_TrueStruct_ptr
inc     qword ptr [r14]
```

这段非常关键，因为它让脚本不需要猜 `__Py_TrueStruct_ptr` 在当前版本中的地址，而是直接复用函数里已经存在的引用方式。

## 5. 如何构造补丁

原始字节在当前样本中是：

```text
e8 c8 c3 ff ff 49 89 c7 48 89 85 50 ff ff ff
```

对应汇编是：

```asm
call    ___Pyx_PyObject_FastCallDict
mov     r15, rax
mov     [rbp-0xb0], rax
```

脚本将其替换为：

```text
4c 8b 3d 26 a3 01 00 4c 89 bd 50 ff ff ff 90
```

对应汇编语义是：

```asm
mov     r15, [rip+disp32]    ; 取 __Py_TrueStruct_ptr
mov     [rbp-0xb0], r15
nop
```

其中第一条指令不是写死的，而是脚本动态生成：

```python
return b"\x4c\x8b\x3d" + struct.pack("<i", disp) + bytes.fromhex(
    "4C 89 BD 50 FF FF FF 90"
)
```

这里的 `disp` 由当前样本里的 `__Py_TrueStruct_ptr` 地址计算得到：

```python
disp = py_true_ptr_vmaddr - (callsite_vmaddr + 7)
```

这样不同版本里即使 `__Py_TrueStruct_ptr` 的实际地址变了，只要函数里还能找到那条 `mov r14, cs:__Py_TrueStruct_ptr`，脚本就能自动重算补丁字节。

## 6. 为什么这样改后会稳定返回 True

补丁后的效果不是“直接从函数里 return”，而是：

1. 本应调用 `___Pyx_PyObject_FastCallDict` 的地方，不再真正调用
2. 直接把 `Py_True` 指针放进 `r15`
3. 同时写入 `[rbp-0xb0]`，保持后续局部变量状态一致
4. 后面代码继续执行既有的清理逻辑
5. 再进入 `0xde14` 开始的成功返回路径

因此在控制流上，它仍然是“沿着原函数的成功分支返回”，只是把真正的验证结果伪造为了成功。

## 7. 关键函数与关键常量

脚本中的几个关键点如下：

### 7.1 目标符号

```python
TARGET_SYMBOL = "___pyx_pw_15about_interface_9MyEncrypt_3checkLicense"
```

### 7.2 补丁点特征

```python
CALLSITE_PATTERN = (
    "E8 ?? ?? ?? ?? 49 89 C7 48 89 85 50 FF FF FF 4D 85 E4 74 0A"
)
```

### 7.3 `Py_True` 加载特征

```python
PY_TRUE_PATTERN = "4C 8B 35 ?? ?? ?? ?? 49 FF 06"
```

### 7.4 核心定位函数

- `parse_macho(path)`
  解析 Mach-O 结构、段表和符号表。

- `find_symbol(info, symbol_name)`
  从符号表中找到 `checkLicense` 包装函数。

- `estimate_function_size(info, symbol)`
  估算函数边界，得到函数体字节范围。

- `find_pattern(blob, pattern)`
  在函数内部用通配模式搜索关键字节序列。

- `locate_patch(info)`
  汇总完成：
  目标函数定位、补丁点查找、`Py_True` 地址解析、补丁字节生成。

- `build_patch(callsite_vmaddr, py_true_ptr_vmaddr)`
  动态计算 RIP 相对位移并生成最终要写入的机器码。

## 8. 输出与安全检查

脚本会在写补丁前做两类检查：

1. 检查输出文件是否已存在
2. 检查补丁点当前字节是否等于定位阶段读到的原始字节

如果当前字节已经是补丁后的内容，会报：

```text
target already appears to be patched
```

如果字节和定位结果不一致，会报：

```text
unexpected bytes at patch site
```

这能避免：

- 对错误版本盲目打补丁
- 对已经被改过的样本重复覆盖
- 因偏移错位导致写坏文件

## 9. 当前样本上的实际结果

在当前样本 `about_interface.so` 上，脚本实际解析结果为：

- 目标符号：`___pyx_pw_15about_interface_9MyEncrypt_3checkLicense`
- 补丁文件偏移：`0xddb3`

原始字节：

```text
e8 c8 c3 ff ff 49 89 c7 48 89 85 50 ff ff ff
```

补丁字节：

```text
4c 8b 3d 26 a3 01 00 4c 89 bd 50 ff ff ff 90
```

## 10. 使用方法

示例：

```bash
python3 patch_about_interface.py \
  ./about_interface.so
```

默认输出为：

```text
about_interface.so.patched
```

也可以手动指定输出文件：

```bash
python3 patch_about_interface.py \
  ./about_interface.so \
  -o /tmp/about_interface_sigpatch.so -f
```

## 11. 兼容性与局限

这个方案比固定偏移更稳，但仍有几个前提：

- Mach-O 必须保留符号表
- 目标符号名必须仍然存在
- `checkLicense` 内部那两段局部指令模式没有被大改

如果以后某个版本：

- 去掉了符号表
- 改了 Cython 生成方式
- 调整了成功返回路径的实现

那么这个脚本就可能无法命中特征，需要重新分析并更新特征码或补丁策略。

## 12. 一句话总结

这个脚本本质上做的是：

> 先通过 Mach-O 符号表定位 `MyEncrypt.checkLicense` 对应的 Cython 包装函数，再在函数内部找到原本用于接收 `rsa.verify(...)` 返回值的位置，把它改成直接装载 `Py_True`，从而让函数沿着原有成功路径稳定返回 `True`。
