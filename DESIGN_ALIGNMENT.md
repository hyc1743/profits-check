# 设计风格统一报告

## 概述
已将当前项目 (profits-check) 的前端设计风格与参考项目 (_reference-crypto-portfolio-tracker-oss) 完全统一。

## 核心设计特征

### 1. **手绘草图风格 (Sketchy Style)**
- 1.5px 实线边框 (`border: 1.5px solid var(--line)`)
- 虚线分隔 (`border-bottom: 1.5px dashed var(--line)`)
- 固定偏移阴影，非模糊阴影 (`box-shadow: 4px 4px 0 var(--line)`)
- 轻微旋转效果 (`transform: rotate(-1deg)`) 用于品牌标记

### 2. **配色系统**
```css
--paper: #f4f4f2         /* 主背景 - 米白色 */
--ink: #1a1814           /* 主文字 - 深褐黑 */
--accent: #d64933        /* 强调色 - 砖红色 */
--accent-2: #2e8b6b      /* 辅助色 - 森林绿 */
--yellow: #f2c14e        /* 黄色高光 */
--purple: #7a5fbd        /* 紫色信息 */
```

深色模式支持：
```css
--paper: #161511         /* 深色背景 */
--ink: #f4f4f2           /* 浅色文字 */
```

### 3. **字体系统**
- **标题字体**: DM Sans (`--head`)
  - font-weight: 500-700
  - letter-spacing: -0.02em (紧凑)
- **等宽字体**: IBM Plex Mono (`--mono`)
  - 用于数据、代码、标签
  - font-size: 0.72rem - 0.82rem

### 4. **圆角系统**
```css
--radius-sm: 6px
--radius-md: 8px
--radius-lg: 10px
--radius-xl: 12px
--radius-full: 999px
```

### 5. **间距与布局**
- 基础间距: 0.75rem - 1rem
- 面板内边距: clamp(1rem, 2vw, 1.35rem)
- 网格间距: 0.75rem - 1rem
- 最大宽度: 1440px (居中)

### 6. **组件特征**

#### 侧边栏 (Side Rail)
- 固定宽度: 5.4rem
- 黄色品牌标记，轻微旋转
- 悬停效果: 背景黄色高光 + 阴影位移

#### 面板 (Panel)
- 统一的 4px 偏移阴影
- 虚线分隔标题
- 渐变背景（可选）

#### 按钮 (Buttons)
- 统一 min-height: 2.75rem
- 悬停: translate(-1px, -1px) + 2px 阴影
- 主按钮: 深色背景
- 次按钮: 绿色半透明背景
- 幽灵按钮: 透明背景

#### 指标卡片 (Metric Cards)
- 第一个卡片: 黄色渐变背景
- 数字: clamp(1.08rem, 2vw, 1.55rem)
- tabular-nums 数字等宽

#### 日历视图
- 7列网格布局
- 绿色背景: 有资产数据
- 黄色背景: 利润数据
- 容器查询实现响应式字体

## 统一文件清单

### ✅ 已统一的文件

1. **`frontend/src/index.css`**
   - CSS 变量定义
   - 全局重置样式
   - 深色模式支持

2. **`frontend/src/App.css`**
   - 所有组件样式
   - 布局系统
   - 响应式断点

3. **`frontend/index.html`**
   - Google Fonts 引入
   - DM Sans + IBM Plex Mono + Caveat + Kalam

## 响应式断点

```css
@media (max-width: 1180px) - 侧边栏转为横向
@media (max-width: 1024px) - 网格变单列
@media (max-width: 640px)  - 移动端优化
```

## 验证

✅ 构建成功 - 无样式错误
✅ 字体已加载 - Google Fonts
✅ 变量系统 - 完全匹配参考项目
✅ 组件样式 - 统一手绘风格
✅ 深色模式 - 支持主题切换

## 下一步建议

1. **测试深色模式** - 验证所有组件在深色模式下的可读性
2. **响应式测试** - 在不同设备尺寸下测试布局
3. **无障碍测试** - 确保键盘导航和屏幕阅读器支持
4. **性能优化** - 考虑字体子集化以减少加载时间

---

生成时间: 2026-06-15
参考项目: _reference-crypto-portfolio-tracker-oss
当前项目: profits-check
