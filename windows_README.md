# Windows 下回填 `about_interface.pyd` 的说明

本文档说明如何使用仓库内现成的 `replace_about_interface_pyd.py`，把你已经修改好的 `about_interface.pyd` 回填进原始的 PyInstaller 单文件 `exe`，输出一个新的测试版 `exe`。

## 1. 适用场景

这个脚本适用于下面这种情况：

1. 你已经有一个原始 `exe`
2. 你已经单独修改好了 `about_interface.pyd`
3. 你想把这个修改后的二进制模块重新放回 `exe` 内部
4. 你希望生成一个新的 `exe` 用于本地验证

## 2. 脚本做了什么

仓库中的脚本路径是：

```text
windows/replace_about_interface_pyd.py
```

它会做下面几件事：

1. 读取原始 `exe`
2. 解析其中的 PyInstaller CArchive
3. 找到内部成员 `app\view\about_interface.pyd`
4. 用你提供的新文件内容替换这个成员
5. 重建归档并输出一个新的 `exe`

你可以把它理解成：

“把修改后的 `about_interface.pyd` 直接回填到原始 `exe` 中，生成 patched exe。”

## 3. 输入和输出

脚本需要三个东西：

1. 原始 `exe`
2. 你修改后的 `about_interface.pyd` 二进制文件
3. 输出的新 `exe` 路径

命令格式如下：

```bash
python3 windows/replace_about_interface_pyd.py \
  "原始.exe" \
  "修改后的 about_interface.pyd" \
  -o "输出的新.exe"
```

## 4. 最常用示例

如果你就在当前仓库根目录下操作，一个常见示例是：

```bash
python3 windows/replace_about_interface_pyd.py \
  "./PikPak Desktop.exe" \
  "./windows/v4.6.5/patched/about_interface.pyd.patched" \
  -o "./PikPak Desktop_patched.exe"
```

执行完成后，会生成一个新的：

```text
./PikPak Desktop_patched.exe
```

原始 `exe` 不会被覆盖。

## 5. 第二个参数不要求放在原目录

这里最容易误解的一点是：

第二个参数只表示“要写回去的二进制内容”，并不要求它在磁盘上的目录结构和程序内部一致。

也就是说，你的补丁文件：

- 不必放在 `app/view/` 目录下
- 不必与解包目录结构一致
- 甚至不必真的叫 `.pyd`

只要这个文件的内容本身，就是你想替换进去的 `about_interface.pyd` 二进制数据即可。

例如你把它放在项目根目录并命名为：

```text
./about_interface.pyd.patched
```

同样可以直接使用：

```bash
python3 windows/replace_about_interface_pyd.py \
  "./PikPak Desktop.exe" \
  "./about_interface.pyd.patched" \
  -o "./PikPak Desktop_patched.exe"
```

脚本不会按扩展名判断文件类型，它只读取你传入文件的原始字节。

## 6. 建议操作顺序

建议按下面顺序操作：

1. 备份原始 `exe`
2. 准备好已经修改完成的 `about_interface.pyd`
3. 运行 `replace_about_interface_pyd.py`
4. 得到新的测试版 `exe`
5. 单独运行新的 `exe` 做验证

推荐保留：

```text
原始.exe
输出的新.exe
```

这样出问题时更容易对比和回滚。


## 10. 适合当前仓库的最短用法

如果你已经准备好了补丁文件，最短流程就是：

```bash
python3 windows/replace_about_interface_pyd.py \
  "./PikPak Desktop.exe" \
  "./about_interface.pyd.patched" \
  -o "./PikPak Desktop_patched.exe"
```


# 注册

激活高级版随便输入任何的128位注册码都能激活成功：AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA