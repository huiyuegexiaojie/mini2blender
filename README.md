# Mini2Blender Importer

[![Blender 3.6](https://img.shields.io/badge/Blender-3.6-blue.svg)](https://www.blender.org/download/releases/3-6/)
[![Python 3.10+](https://img.shields.io/badge/Python-3.10+-green.svg)](https://www.python.org/)
[![License MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

一个专为 Blender 3.6 设计的插件，可将迷你世界导出的 CSV 方块数据还原为三维模型，支持纹理贴图、纯色材质、特殊模型渲染，并通过**贪婪网格化算法**大幅优化模型面数，提升性能。

---

## ✨ 核心特性

- 🧱 **完整方块还原**：支持迷你世界多种基础形状（立方体、楼梯、斜板、弧板、棱柱、棱锥等）
- 🎨 **材质系统**：
  - 自动加载纹理贴图（PNG 格式）
  - 纯色材质支持（玻璃、棉花、水泥块 RGB 配色）
  - 长草土块特殊处理（顶面/侧面/底面独立贴图）
- ⚡ **性能优化**：贪婪网格化算法合并同材质相邻面，面数最高可减少 90% 以上
- 🎯 **坐标适配**：自动转换迷你世界坐标系到 Blender 坐标系
- 📁 **流式加载**：按需加载 OBJ 模型和纹理，降低内存占用
- 🧩 **特殊模型支持**：自定义特殊模型导入与材质适配

---

## 📋 前置要求

- Blender 3.6.x（推荐 3.6 LTS 版本）
- 迷你世界导出的 CSV 方块数据文件
- 配套的纹理贴图（PNG）、OBJ 模型文件
- 颜色映射字典文件（玻璃 / 棉花 / 水泥块 RGB 配置）

---

## 📂 项目结构

```text
Mini2Blender/
├── mini2blender.py          # 主插件文件
├── textures/                # 纹理贴图文件夹
│   ├── 长草土块顶面.png
│   ├── 长草土块侧面.png
│   ├── 长草土块底面.png
│   └── 其他方块贴图.png
├── objs/                    # 基础形状 OBJ 模型文件夹
│   ├── 立方体.obj
│   ├── 楼梯.obj
│   └── 其他基础形状.obj
├── special_objs/            # 特殊模型 OBJ 文件夹
├── color_maps/              # 颜色映射字典文件夹
│   ├── 玻璃块RGB字典.txt
│   ├── 棉花块RGB字典.txt
│   └── 上色水泥块RGB字典.txt
├── special_dict.txt         # 特殊模型映射字典
└── README.md                # 使用说明
