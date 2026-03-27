# macOS 下替换 `about_interface.so` 使补丁生效的说明

本文档说明在 macOS 下，如何将已经 patch 好的 `about_interface.so` 放回应用包中并覆盖原文件，使修改生效。

## 1. 目标文件在 App 包中的位置

当前样本里，应用包内的目标文件路径是：

```text
PikPak Desktop.app/Contents/MacOS/app/view/about_interface.so
```

如果你要替换的是安装在 `/Applications` 里的正式应用，那么目标路径通常会是：

```text
/Applications/PikPak Desktop.app/Contents/MacOS/app/view/about_interface.so
```

## 2. 生效原理

这个 `.so` 文件是应用运行时从 `.app` 包内加载的 Python 扩展模块。

因此要让补丁生效，关键不是把 patch 后的文件单独放在别处，而是：

1. 找到 App 包内实际被加载的 `about_interface.so`
2. 用 patch 后的文件覆盖它
3. 重新启动应用

只要应用启动时加载到的是你替换后的 `.so`，补丁就会生效。

## 3. 建议的操作顺序

建议按下面顺序操作：

1. 完全退出应用
2. 备份原始 `about_interface.so`
3. 用补丁脚本生成 patch 后的 `.so`
4. 将 patch 后的文件覆盖到 App 包内目标路径
5. 重新启动应用验证效果

## 4. 先生成 patch 后的文件

假设你已经有：

- 原始文件：`./about_interface.so`
- 补丁脚本：`./patch_about_interface.py`

可以先生成一个 patch 后的新文件：

```bash
python3 ./patch_about_interface.py \
  ./about_interface.so \
  -o ./about_interface.so.patched -f
```

生成后的文件路径是：

```text
./about_interface.so.patched
```

## 5. 覆盖到当前工作目录里的 App 样本

如果你要替换的是当前工作目录里的这个应用包：

```text
./PikPak Desktop.app
```

那么可以执行：

```bash
cp \
  "./PikPak Desktop.app/Contents/MacOS/app/view/about_interface.so" \
  "./PikPak Desktop.app/Contents/MacOS/app/view/about_interface.so.bak"
```

然后覆盖原文件：

```bash
cp \
  ./about_interface.so.patched \
  "./PikPak Desktop.app/Contents/MacOS/app/view/about_interface.so"
```

这样就完成了替换。

## 6. 覆盖到 `/Applications` 里的正式 App

如果你要替换的是系统里真正安装的应用，常见路径是：

```text
/Applications/PikPak Desktop.app/Contents/MacOS/app/view/about_interface.so
```

通常这个目录需要管理员权限，因此建议用 `sudo`。

先备份：

```bash
sudo cp \
  "/Applications/PikPak Desktop.app/Contents/MacOS/app/view/about_interface.so" \
  "/Applications/PikPak Desktop.app/Contents/MacOS/app/view/about_interface.so.bak"
```

再覆盖：

```bash
sudo cp \
  ./about_interface.so.patched \
  "/Applications/PikPak Desktop.app/Contents/MacOS/app/view/about_interface.so"
```

## 7. 替换后如何生效

替换完成后，重新启动应用即可。

如果应用在替换时仍然开着，有几种情况：

- 进程已经把旧 `.so` 加载进内存，替换后本次运行不会立刻生效
- 只有在完全退出并重新启动后，才会重新从磁盘加载新的 `.so`

所以最稳妥的方式是：

1. 先退出应用
2. 再替换文件
3. 再重新打开应用

## 8. 额外注意事项

### 8.1 macOS 应用签名可能失效

修改 `.app` 包内部文件后，应用原本的代码签名可能会失效。

这意味着：

- 有些应用仍然能直接运行
- 有些情况下 Finder 启动会被系统阻止
- 某些环境下可能出现“已损坏”或无法验证开发者之类的提示

如果你只是对当前工作目录里的样本做本地测试，通常问题不大。

如果你替换的是 `/Applications` 里的正式 App，macOS 可能会更严格。

### 8.2 最好保留原文件备份

建议始终保留：

```text
about_interface.so.bak
```

这样如果替换后应用异常，可以直接恢复：

```bash
cp about_interface.so.bak about_interface.so
```

或者在 `/Applications` 场景下：

```bash
sudo cp \
  "/Applications/PikPak Desktop.app/Contents/MacOS/app/view/about_interface.so.bak" \
  "/Applications/PikPak Desktop.app/Contents/MacOS/app/view/about_interface.so"
```

### 8.3 不要只替换工作目录里的独立 `.so`

仅仅修改：

```text
./about_interface.so
```

本身不会让应用自动生效，除非应用运行时实际加载的就是这个文件。

当前这个 App 真正加载的是包内的：

```text
./PikPak Desktop.app/Contents/MacOS/app/view/about_interface.so
```

所以要以 App 包内路径为准。

## 9. 最简操作示例

如果你只是想最快完成一次替换并测试，可以按下面执行：

```bash
python3 ./patch_about_interface.py \
  ./about_interface.so \
  -o ./about_interface.so.patched -f
```

```bash
cp \
  "./PikPak Desktop.app/Contents/MacOS/app/view/about_interface.so" \
  "./PikPak Desktop.app/Contents/MacOS/app/view/about_interface.so.bak"
```

```bash
cp \
  ./about_interface.so.patched \
  "./PikPak Desktop.app/Contents/MacOS/app/view/about_interface.so"
```

然后重新启动 `PikPak Desktop.app`。

# 注册

激活高级版随便输入任何的128位注册码都能激活成功：AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA