# Profits Check 设计指南

本项目的前端设计风格已与参考项目完全统一，采用**手绘草图风格 (Sketchy/Wireframe Style)**。

## 🎨 设计原则

### 视觉风格
- **手绘感**: 使用实线边框、虚线分隔、固定偏移阴影
- **温暖色调**: 米白色背景 + 深褐色文字 + 砖红/森林绿强调色
- **等宽数字**: 所有数据使用 tabular-nums 确保对齐
- **适度动画**: 仅悬停时有位移和阴影变化 (140ms ease)

### 设计语言
```
草图本 + 数据看板 + 金融工具的混合体
```

## 🎯 关键设计元素

### 边框与阴影
```css
/* 标准边框 */
border: 1.5px solid var(--line);

/* 虚线分隔 */
border-bottom: 1.5px dashed var(--line);

/* 固定偏移阴影（非模糊） */
box-shadow: 4px 4px 0 var(--line);

/* 悬停效果 */
transform: translate(-1px, -1px);
box-shadow: 2px 2px 0 var(--line);
```

### 色彩使用场景

| 颜色 | 变量 | 用途 |
|------|------|------|
| 🟡 黄色 | `--yellow: #f2c14e` | 品牌标记、高光、正向利润 |
| 🔴 砖红 | `--accent: #d64933` | 主强调色、错误、警告 |
| 🟢 森林绿 | `--accent-2: #2e8b6b` | 成功、增长、确认 |
| 🟣 紫色 | `--purple: #7a5fbd` | 信息提示、ADL 检测 |

### 字体层级
```css
/* 大标题 */
h1 {
  font-family: var(--head);  /* DM Sans */
  font-size: clamp(2.5rem, 5.4vw, 4.75rem);
  font-weight: 500;
  letter-spacing: -0.02em;
}

/* 数据数字 */
.metric-card strong {
  font-family: var(--head);
  font-size: clamp(1.08rem, 2vw, 1.55rem);
  font-weight: 600;
  font-variant-numeric: tabular-nums;
}

/* 标签文字 */
.metric-card span {
  font-family: var(--mono);  /* IBM Plex Mono */
  font-size: 0.72rem;
  letter-spacing: 0.07em;
  text-transform: uppercase;
}
```

## 📐 组件规范

### 侧边栏导航
```
宽度: 5.4rem (紧凑)
品牌标记: 黄色背景 + 轻微旋转 (-1deg)
按钮: 居中对齐 + 悬停黄色高光
```

### 指标卡片
```
第一张卡片: 黄色渐变背景（强调总资产）
其他卡片: 白色背景
最小高度: 5.75rem
数字: 自适应大小 (clamp)
```

### 按钮系统
```css
/* 主按钮 - 深色填充 */
.button-primary {
  background: var(--ink);
  color: var(--paper);
}

/* 次按钮 - 绿色半透明 */
.button-secondary {
  background: rgba(46, 139, 107, 0.12);
  color: var(--accent-2);
}

/* 幽灵按钮 - 透明 */
.button-ghost {
  background: transparent;
}

/* 危险按钮 - 红色填充 */
.button-danger {
  background: var(--danger);
  color: var(--contrast-on-danger);
}
```

### 日历网格
```css
/* 7列布局 */
grid-template-columns: repeat(7, minmax(0, 1fr));

/* 有数据: 绿色背景 */
.calendar-day-has-value {
  background: rgba(46, 139, 107, 0.12);
}

/* 利润数据: 黄色背景 */
.profit-day {
  background: rgba(242, 193, 78, 0.22);
}
```

## 🌙 深色模式

### 颜色反转
```css
/* 浅色模式 */
--paper: #f4f4f2;  /* 米白 */
--ink: #1a1814;    /* 深褐 */

/* 深色模式 */
--paper: #161511;  /* 深褐黑 */
--ink: #f4f4f2;    /* 米白 */
```

### 使用方式
```typescript
// 在 App.tsx 中切换
document.documentElement.dataset.theme = 'dark' | 'light'
```

## 📱 响应式设计

### 断点系统
```css
/* 桌面 (> 1180px) */
侧边栏: 垂直固定

/* 平板 (≤ 1180px) */
侧边栏: 转为横向布局

/* 小平板 (≤ 1024px) */
网格: 全部单列
卡片: 堆叠显示

/* 移动端 (≤ 640px) */
间距: 压缩
字体: 缩小
```

## 🎭 动画规范

### 悬停效果
```css
transition: background-color 140ms ease, 
            transform 140ms ease, 
            box-shadow 140ms ease;
```

### 进入动画
```css
@keyframes field-fade-in {
  from {
    opacity: 0;
    transform: translateY(-6px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}
```

### 无障碍
```css
@media (prefers-reduced-motion: reduce) {
  * {
    animation-duration: 0.01ms !important;
    transition-duration: 0.01ms !important;
  }
}
```

## ✅ 设计检查清单

新组件设计时，确保：

- [ ] 使用 1.5px 实线边框
- [ ] 虚线分隔代替实线
- [ ] 4px 偏移阴影（非模糊）
- [ ] 数字使用 tabular-nums
- [ ] 悬停有位移 + 阴影变化
- [ ] 支持深色模式
- [ ] 响应式友好
- [ ] 键盘可访问
- [ ] 颜色对比度 ≥ 4.5:1

## 🔧 开发工具

### CSS 变量快速查询
```bash
# 查看所有颜色变量
grep -E "^\s*--[a-z-]+:" src/index.css | head -20

# 查看圆角变量
grep "radius" src/index.css
```

### 样式验证
```bash
# 构建检查
bun run build

# 类型检查
bun run typecheck

# 代码规范
bun run lint
```

---

**参考**: `/root/projects/_reference-crypto-portfolio-tracker-oss`
**更新时间**: 2026-06-15
