# 插件名称: Mini2Blender Importer
# 支持版本: Blender 3.6
# 功能: 将迷你世界导出的CSV方块数据还原为Blender三维模型，支持纹理贴图、纯色材质、特殊模型和长草土块
# 核心优化: 贪婪网格化算法合并同材质相邻面，大幅减少面数

bl_info = {
    "name": "Mini2Blender 模型导入器",
    "author": "基于用户脚本改造",
    "version": (2, 0, 0),
    "blender": (3, 6, 0),
    "location": "3D视图 > 侧边栏 > Mini2Blender",
    "description": "将迷你世界CSV方块数据还原为Blender模型，支持纹理贴图、纯色材质和贪婪网格化优化",
    "category": "Import-Export",
}

import bpy
import bmesh
import csv
import os
import tempfile
from mathutils import Matrix, Vector
from collections import defaultdict

# ===================== 全局配置（动态赋值，运行时根据根目录更新）=====================
ROOT_PATH = ""
CSV_FILE_PATH = ""
OBJ_FOLDER_PATH = ""
TEXTURE_FOLDER_PATH = ""
COLOR_MAP_PATH = ""
SPECIAL_OBJ_FOLDER = ""
SPECIAL_DICT_PATH = ""

# 优化配置（保留原设置）
WELD_THRESHOLD = 0.001
ENABLE_INTERNAL_FACE_CULL = True
ENABLE_VERTEX_WELD = True
ENABLE_BASIC_CLEANUP = True

# 长草土块贴图配置
GRASS_TOP_NAME = "长草土块顶面.png"
GRASS_SIDE_NAME = "长草土块侧面.png"
GRASS_BOTTOM_NAME = "长草土块底面.png"
GRASS_TOP_PATH = ""
GRASS_SIDE_PATH = ""
GRASS_BOTTOM_PATH = ""

# 坐标变换矩阵
C_MATRIX = Matrix([[1, 0, 0], [0, 0, 1], [0, 1, 0]])
C_MATRIX_INV = C_MATRIX.inverted()
BASE_SHAPE_LIST = [
    "大竖薄弧板", "大竖薄斜板", "竖大薄弧板", "竖大薄斜板",
    "大薄弧板", "大薄斜板", "竖薄弧板", "竖薄斜板", "竖薄板", "竖板",
    "薄弧板", "薄斜板", "薄板", "弧板", "斜板", "楼梯", "棱柱", "棱锥", "立方体"
]
DIRECTION_DICT = {
    0: Vector((1, 0, 0)), 1: Vector((0, 0, -1)),
    2: Vector((-1, 0, 0)), 3: Vector((0, 0, 1))
}
UP_NORMAL = Vector((0, 1, 0))
DOWN_NORMAL = Vector((0, -1, 0))
THICKNESS_PREFIX_QUARTER = ["四分之一", "四分之二", "四分之三", "四分之四"]
THICKNESS_PREFIX_HALF = ["二分之一", "二分之二"]

# ===================== Data映射表 =====================
DATA_MAP_A = {1:(0,False),2:(1,False),0:(2,False),3:(3,False),5:(0,True),6:(1,True),4:(2,True),7:(3,True)}
DATA_MAP_B_INV = {4:(0,True),1:(1,True),6:(1,True),7:(3,True)}
DATA_MAP_B_NOR = {3:(0,False),0:(1,False),5:(2,False),2:(3,False)}
DATA_MAP_C = {1:(0,0),5:(0,1),9:(0,2),13:(0,3),2:(1,0),6:(1,1),10:(1,2),14:(1,3),0:(2,0),4:(2,1),8:(2,2),12:(2,3),3:(3,0),7:(3,1),11:(3,2),15:(3,3)}
DATA_MAP_D = {1:(0,0),9:(0,1),2:(1,0),10:(1,1),0:(2,0),8:(2,1),3:(3,0),11:(3,1)}
DATA_MAP_E_INV = {5:(0,0,True),13:(0,1,True),6:(1,0,True),14:(1,1,True),4:(2,0,True),12:(2,1,True),7:(3,0,True),15:(3,1,True)}
DATA_MAP_E_NOR = {1:(0,0,False),9:(0,1,False),2:(1,0,False),10:(1,1,False),0:(2,0,False),8:(2,1,False),3:(3,0,False),11:(3,1,False)}
SHAPE_TYPE_MAP = {"a":["楼梯","弧板","斜板","棱柱","棱锥"],"b":["薄板"],"c":["竖薄板"],"d":["竖板"],"e":["薄弧板","薄斜板","竖薄弧板","竖薄斜板"]}

# ===================== 全局缓存（每次生成前重置）=====================
MESH_CACHE = {}
MISSING_OBJ_CACHE = set()
MISSING_SPECIAL_CACHE = set()
MATERIAL_CACHE = {}
ALL_TEXTURE_FILES = []
COLOR_MAP_CACHE = {}
GRASS_MATS = None
OBJ_DICT = {}
SPECIAL_NAMES = set()
SPECIAL_MESH_CACHE = {}
SPECIAL_MATERIAL_CACHE = {}

# ===================== 辅助函数：重置全局缓存 =====================
def reset_global_caches():
    global MESH_CACHE, MISSING_OBJ_CACHE, MISSING_SPECIAL_CACHE, MATERIAL_CACHE
    global ALL_TEXTURE_FILES, COLOR_MAP_CACHE, GRASS_MATS, OBJ_DICT, SPECIAL_NAMES
    global SPECIAL_MESH_CACHE, SPECIAL_MATERIAL_CACHE
    MESH_CACHE = {}
    MISSING_OBJ_CACHE = set()
    MISSING_SPECIAL_CACHE = set()
    MATERIAL_CACHE = {}
    ALL_TEXTURE_FILES = []
    COLOR_MAP_CACHE = {}
    GRASS_MATS = None
    OBJ_DICT = {}
    SPECIAL_NAMES = set()
    SPECIAL_MESH_CACHE = {}
    SPECIAL_MATERIAL_CACHE = {}

# ===================== 材质与图片工具 =====================
def load_image(filepath):
    abs_path = bpy.path.abspath(filepath)
    for img in bpy.data.images:
        if img.filepath == abs_path:
            return img
    img = bpy.data.images.load(abs_path)
    img.colorspace_settings.name = 'sRGB'
    return img

def create_material(name, image, pixel_perfect):
    if name in bpy.data.materials:
        return bpy.data.materials[name]
    mat = bpy.data.materials.new(name=name)
    mat.use_nodes = True
    mat.blend_method = 'OPAQUE'
    mat.shadow_method = 'OPAQUE'
    nodes = mat.node_tree.nodes
    links = mat.node_tree.links
    for n in nodes: nodes.remove(n)
    bsdf = nodes.new(type='ShaderNodeBsdfPrincipled')
    bsdf.location = (0, 0)
    bsdf.inputs['Specular'].default_value = 0.0
    bsdf.inputs['Roughness'].default_value = 1.0
    bsdf.inputs['Metallic'].default_value = 0.0
    tex_node = nodes.new(type='ShaderNodeTexImage')
    tex_node.image = image
    tex_node.location = (-300, 0)
    tex_node.extension = 'REPEAT'
    if pixel_perfect: tex_node.interpolation = 'Closest'
    output = nodes.new(type='ShaderNodeOutputMaterial')
    output.location = (300, 0)
    links.new(tex_node.outputs['Color'], bsdf.inputs['Base Color'])
    links.new(bsdf.outputs['BSDF'], output.inputs['Surface'])
    return mat

def create_material_with_mix(name, image, pixel_perfect):
    if name in bpy.data.materials:
        return bpy.data.materials[name]
    mat = bpy.data.materials.new(name=name)
    mat.use_nodes = True
    mat.blend_method = 'OPAQUE'
    mat.shadow_method = 'OPAQUE'
    nodes = mat.node_tree.nodes
    links = mat.node_tree.links
    for n in nodes: nodes.remove(n)
    tex_node = nodes.new(type='ShaderNodeTexImage')
    tex_node.image = image
    tex_node.location = (-500, 0)
    tex_node.extension = 'REPEAT'
    if pixel_perfect: tex_node.interpolation = 'Closest'
    mix_rgb = nodes.new(type='ShaderNodeMixRGB')
    mix_rgb.location = (-200, 0)
    mix_rgb.blend_type = 'MULTIPLY'
    mix_rgb.inputs['Fac'].default_value = 1.0
    mix_rgb.inputs['Color1'].default_value = (1, 1, 1, 1)
    mix_rgb.inputs['Color2'].default_value = (0.023, 0.156, 0.0, 1.0)
    bsdf = nodes.new(type='ShaderNodeBsdfPrincipled')
    bsdf.location = (100, 0)
    bsdf.inputs['Metallic'].default_value = 0.0
    bsdf.inputs['Roughness'].default_value = 1.0
    bsdf.inputs['Specular'].default_value = 0.0
    output = nodes.new(type='ShaderNodeOutputMaterial')
    output.location = (400, 0)
    links.new(tex_node.outputs['Color'], mix_rgb.inputs['Color1'])
    links.new(mix_rgb.outputs['Color'], bsdf.inputs['Base Color'])
    links.new(bsdf.outputs['BSDF'], output.inputs['Surface'])
    return mat

def get_grass_block_materials():
    global GRASS_MATS
    if GRASS_MATS is not None: return GRASS_MATS
    force_pixel = True
    img_top = load_image(GRASS_TOP_PATH)
    img_side = load_image(GRASS_SIDE_PATH)
    img_bottom = load_image(GRASS_BOTTOM_PATH)
    mat_top = create_material_with_mix("草顶面", img_top, force_pixel)
    mat_side = create_material("草侧面", img_side, force_pixel)
    mat_bottom = create_material("草底面", img_bottom, force_pixel)
    GRASS_MATS = (mat_top, mat_side, mat_bottom)
    return GRASS_MATS

# ===================== 方块类型判断 =====================
def is_grass_block(name):
    return "长草土块" in name or "草方块" in name

def get_block_type(block_name):
    if block_name in SPECIAL_NAMES: return "special"
    if is_grass_block(block_name): return "grass_block"
    if "玻璃块" in block_name or "glass" in block_name.lower(): return "glass"
    if "棉花块" in block_name or "cotton" in block_name.lower(): return "cotton"
    if "上色水泥块" in block_name or "水泥块" in block_name or "concrete" in block_name.lower(): return "concrete"
    return "normal"

# ===================== 颜色字典 =====================
def load_color_maps():
    global COLOR_MAP_CACHE
    color_map_config = {
        "glass": "玻璃块RGB字典.txt",
        "cotton": "棉花块RGB字典.txt",
        "concrete": "上色水泥块RGB字典.txt"
    }
    for block_type, file_name in color_map_config.items():
        file_full_path = os.path.join(COLOR_MAP_PATH, file_name)
        if not os.path.exists(file_full_path):
            COLOR_MAP_CACHE[block_type] = {}
            continue
        try:
            with open(file_full_path, 'r', encoding='utf-8') as f:
                file_content = f.read()
            local_env = {}
            exec(file_content, {}, local_env)
            if block_type == "glass": rgb_dict = local_env.get("glass_rgb", {})
            elif block_type == "cotton": rgb_dict = local_env.get("cotton_rgb", {})
            elif block_type == "concrete": rgb_dict = local_env.get("concrete_rgb", {})
            else: rgb_dict = {}
            COLOR_MAP_CACHE[block_type] = rgb_dict
        except Exception as e:
            COLOR_MAP_CACHE[block_type] = {}

def get_block_rgb(block_type, block_id, data):
    rgb_dict = COLOR_MAP_CACHE.get(block_type, {})
    dict_key = (block_id, data)
    if dict_key in rgb_dict: return rgb_dict[dict_key]
    return (128, 128, 128)

# ===================== 纯色材质 =====================
def get_or_create_color_material(block_type, block_id, data):
    material_name = f"MI_{block_type}_{block_id}_{data}"
    if material_name in MATERIAL_CACHE: return MATERIAL_CACHE[material_name]
    r_255, g_255, b_255 = get_block_rgb(block_type, block_id, data)
    r, g, b = r_255/255.0, g_255/255.0, b_255/255.0
    mat = bpy.data.materials.new(name=material_name)
    mat.use_nodes = True
    nodes = mat.node_tree.nodes
    links = mat.node_tree.links
    for node in nodes: nodes.remove(node)
    node_bsdf = nodes.new(type='ShaderNodeBsdfPrincipled')
    node_output = nodes.new(type='ShaderNodeOutputMaterial')
    node_bsdf.location = (-200, 0)
    node_output.location = (200, 0)
    if block_type == "glass":
        mat.blend_method = 'BLEND'
        mat.shadow_method = 'HASHED'
        node_bsdf.inputs['Base Color'].default_value = (r, g, b, 1.0)
        node_bsdf.inputs['Transmission'].default_value = 0.95
        node_bsdf.inputs['Roughness'].default_value = 0.02
        node_bsdf.inputs['IOR'].default_value = 1.45
        node_bsdf.inputs['Alpha'].default_value = 0.3
        node_bsdf.inputs['Specular'].default_value = 1.0
    else:
        mat.blend_method = 'OPAQUE'
        mat.shadow_method = 'OPAQUE'
        node_bsdf.inputs['Base Color'].default_value = (r, g, b, 1.0)
        node_bsdf.inputs['Roughness'].default_value = 0.9
        node_bsdf.inputs['Specular'].default_value = 0.1
        node_bsdf.inputs['Alpha'].default_value = 1.0
    links.new(node_bsdf.outputs['BSDF'], node_output.inputs['Surface'])
    MATERIAL_CACHE[material_name] = mat
    return mat

# ===================== UV工具（旧，保留以兼容非立方体） =====================
def calculate_block_uv(vert_co_local, normal_key):
    nx, ny, nz = normal_key
    x, y, z = vert_co_local
    if nx == 1: u, v = 1-z, y
    elif nx == -1: u, v = z, y
    elif ny == 1: u, v = x, z
    elif ny == -1: u, v = 1-x, z
    elif nz == 1: u, v = x, 1-y
    elif nz == -1: u, v = x, y
    else: u, v = x, y
    return (u, v)

def apply_cube_uv(mesh, block_size=1):
    bm = bmesh.new()
    bm.from_mesh(mesh)
    if not bm.loops.layers.uv: bm.loops.layers.uv.new()
    uv_layer = bm.loops.layers.uv.active
    face_groups = defaultdict(list)
    for face in bm.faces:
        normal = face.normal.normalized()
        normal_key = (round(normal.x), round(normal.y), round(normal.z))
        face_groups[normal_key].append(face)
    for normal_key, faces in face_groups.items():
        for face in faces:
            for loop in face.loops:
                co_local = (loop.vert.co / block_size) + Vector((0.5, 0.5, 0.5))
                loop[uv_layer].uv = calculate_block_uv(co_local, normal_key)
    bm.to_mesh(mesh)
    bm.free()
    mesh.update()
    return mesh

# ===================== 【核心】普通OBJ 流动式加载 =====================
def load_obj_mesh(obj_filename):
    if obj_filename in MESH_CACHE:
        return MESH_CACHE[obj_filename]
    if obj_filename in MISSING_OBJ_CACHE:
        return None
    
    obj_file_path = os.path.join(OBJ_FOLDER_PATH, obj_filename)
    if not os.path.exists(obj_file_path):
        print(f"❌ [缺失] OBJ文件不存在：{obj_filename}")
        MISSING_OBJ_CACHE.add(obj_filename)
        return None
        
    print(f"🚀 [流式加载] 正在加载普通方块模型：{obj_filename}")
    try:
        bpy.ops.import_scene.obj(filepath=obj_file_path)
        imported_objects = bpy.context.selected_objects
        if not imported_objects:
            MISSING_OBJ_CACHE.add(obj_filename)
            return None
        mesh_obj = imported_objects[0]
        mesh_data = mesh_obj.data.copy()
        mesh_data.name = f"mesh_{obj_filename}"
        bpy.ops.object.delete()
        mesh_data = apply_cube_uv(mesh_data)
        MESH_CACHE[obj_filename] = mesh_data
        print(f"✅ [流式加载] 成功加载：{obj_filename}")
        return mesh_data
    except Exception as e:
        print(f"❌ [加载失败] {obj_filename}: {str(e)}")
        MISSING_OBJ_CACHE.add(obj_filename)
        return None

# ===================== 【核心】特殊模型 流动式加载 =====================
def load_special_mesh(obj_filename):
    if obj_filename in SPECIAL_MESH_CACHE:
        return SPECIAL_MESH_CACHE[obj_filename]
    if obj_filename in MISSING_SPECIAL_CACHE:
        return None
        
    obj_path = os.path.join(SPECIAL_OBJ_FOLDER, obj_filename)
    if not os.path.exists(obj_path):
        print(f"❌ [缺失] 特殊模型文件不存在：{obj_filename}")
        MISSING_SPECIAL_CACHE.add(obj_filename)
        return None
        
    print(f"🚀 [流式加载] 正在加载特殊模型：{obj_filename}")
    tmp_path = None
    try:
        with open(obj_path, 'r', encoding='utf-8', errors='ignore') as f:
            lines = f.readlines()
        cleaned_lines = [line for line in lines if not line.lstrip().lower().startswith('mtllib')]
        
        with tempfile.NamedTemporaryFile(mode='w', suffix='.obj', delete=False, encoding='utf-8') as tmp:
            tmp.writelines(cleaned_lines)
            tmp_path = tmp.name
            
        bpy.ops.import_scene.obj(filepath=tmp_path)
        imported = bpy.context.selected_objects
        if not imported:
            MISSING_SPECIAL_CACHE.add(obj_filename)
            return None
            
        mesh_obj = imported[0]
        bm = bmesh.new()
        bm.from_mesh(mesh_obj.data)
        
        if bm.verts:
            min_corner = Vector((float('inf'), float('inf'), float('inf')))
            max_corner = Vector((float('-inf'), float('-inf'), float('-inf')))
            for v in bm.verts:
                min_corner.x = min(min_corner.x, v.co.x)
                min_corner.y = min(min_corner.y, v.co.y)
                min_corner.z = min(min_corner.z, v.co.z)
                max_corner.x = max(max_corner.x, v.co.x)
                max_corner.y = max(max_corner.y, v.co.y)
                max_corner.z = max(max_corner.z, v.co.z)
            center = (min_corner + max_corner) / 2.0
        else:
            center = Vector((0, 0, 0))
            
        for v in bm.verts:
            v.co = v.co - center
            v.co *= 0.01
            v.co = C_MATRIX @ v.co
            
        uv_layer = bm.loops.layers.uv.active
        if not uv_layer: bm.loops.layers.uv.new()
        bm.normal_update()
        
        new_mesh = bpy.data.meshes.new(f"special_mesh_{obj_filename}")
        bm.to_mesh(new_mesh)
        bm.free()
        bpy.ops.object.delete()
        
        SPECIAL_MESH_CACHE[obj_filename] = new_mesh
        print(f"✅ [流式加载] 成功加载特殊模型：{obj_filename}")
        return new_mesh
    except Exception as e:
        print(f"❌ [加载失败] 特殊模型 {obj_filename}: {str(e)}")
        MISSING_SPECIAL_CACHE.add(obj_filename)
        return None
    finally:
        if tmp_path and os.path.exists(tmp_path):
            try: os.unlink(tmp_path)
            except: pass

# ===================== 特殊模型材质 =====================
def get_or_create_special_material(obj_filename):
    mat_name = f"MI_special_{obj_filename.replace('.obj','')}"
    if mat_name in SPECIAL_MATERIAL_CACHE:
        return SPECIAL_MATERIAL_CACHE[mat_name]
    
    texture_name = obj_filename.replace('.obj', '.png')
    texture_path = os.path.join(TEXTURE_FOLDER_PATH, texture_name)
    mat = bpy.data.materials.new(name=mat_name)
    mat.use_nodes = True
    mat.blend_method = 'CLIP'
    mat.shadow_method = 'CLIP'
    mat.alpha_threshold = 0.5
    
    nodes = mat.node_tree.nodes
    links = mat.node_tree.links
    for node in nodes: nodes.remove(node)
    
    bsdf = nodes.new(type='ShaderNodeBsdfPrincipled')
    bsdf.location = (0, 0)
    bsdf.inputs['Roughness'].default_value = 0.8
    bsdf.inputs['Specular'].default_value = 0.1
    
    tex_node = nodes.new(type='ShaderNodeTexImage')
    tex_node.location = (-300, 0)
    
    if os.path.exists(texture_path):
        img = bpy.data.images.load(texture_path)
        img.colorspace_settings.name = 'sRGB'
        tex_node.image = img
    
    output = nodes.new(type='ShaderNodeOutputMaterial')
    output.location = (300, 0)
    
    links.new(tex_node.outputs['Color'], bsdf.inputs['Base Color'])
    links.new(tex_node.outputs['Alpha'], bsdf.inputs['Alpha'])
    links.new(bsdf.outputs['BSDF'], output.inputs['Surface'])
    
    SPECIAL_MATERIAL_CACHE[mat_name] = mat
    return mat

# ===================== 特殊模型字典加载 =====================
def load_special_obj_dict():
    global OBJ_DICT, SPECIAL_NAMES
    if not os.path.exists(SPECIAL_DICT_PATH):
        return
    try:
        with open(SPECIAL_DICT_PATH, 'r', encoding='utf-8') as f:
            file_content = f.read()
        local_vars = {}
        exec(file_content, {}, local_vars)
        OBJ_DICT = local_vars.get("obj_dict", {})
        SPECIAL_NAMES = {key.replace('.obj', '') for key in OBJ_DICT}
        print(f"✅ 特殊模型字典加载完成（仅索引，未加载模型）")
    except Exception as e:
        OBJ_DICT = {}
        SPECIAL_NAMES = set()

# ===================== 形状解析工具 =====================
def get_base_shape(name):
    if "三棱柱" in name: return "棱柱","棱柱",False
    for shape in BASE_SHAPE_LIST:
        if shape in name:
            return shape, shape.replace("大",""), "大" in name
    return "立方体","立方体",False

def parse_data_value(base_shape, data):
    if base_shape == "立方体": return 0,0,False
    shape_type = None
    for st, shapes in SHAPE_TYPE_MAP.items():
        if base_shape in shapes:
            shape_type = st
            break
    if shape_type == "a":
        if data in DATA_MAP_A: d,u = DATA_MAP_A[data]; return 0,d,u
    elif shape_type == "b":
        if data in DATA_MAP_B_INV: t,u=DATA_MAP_B_INV[data]; return t,0,u
        elif data in DATA_MAP_B_NOR: t,u=DATA_MAP_B_NOR[data]; return t,0,u
    elif shape_type == "c":
        if data in DATA_MAP_C: d,t=DATA_MAP_C[data]; return t,d,False
    elif shape_type == "d":
        if data in DATA_MAP_D: d,t=DATA_MAP_D[data]; return t,d,False
    elif shape_type == "e":
        if data in DATA_MAP_E_INV: d,t,u=DATA_MAP_E_INV[data]; return t,d,u
        elif data in DATA_MAP_E_NOR: d,t,u=DATA_MAP_E_NOR[data]; return t,d,u
    return 0,0,False

def generate_obj_filename(original_shape, thickness_index):
    base_shape = original_shape.replace("大","")
    if base_shape in ["薄板","竖薄板"]:
        prefix = THICKNESS_PREFIX_QUARTER[thickness_index]
    elif base_shape in ["竖板", "薄弧板", "薄斜板","竖薄弧板","竖薄斜板"]:
        prefix = THICKNESS_PREFIX_HALF[thickness_index]
    else:
        prefix = ""
    return f"{prefix}{original_shape}.obj" if prefix else f"{original_shape}.obj"

def calculate_world_matrix(x,y,z,direction_index,upside_down):
    mini_pos = Vector((x,y,z))
    blender_pos = C_MATRIX @ mini_pos
    forward = DIRECTION_DICT[direction_index]
    up = DOWN_NORMAL if upside_down else UP_NORMAL
    right = up.cross(forward)
    mini_rot_matrix = Matrix([[forward.x,right.x,up.x],[forward.y,right.y,up.y],[forward.z,right.z,up.z]])
    blender_rot_matrix = C_MATRIX @ mini_rot_matrix @ C_MATRIX_INV
    translation_matrix = Matrix.Translation(blender_pos)
    return translation_matrix @ blender_rot_matrix.to_4x4()

# ===================== 贴图查找 =====================
def preload_all_textures():
    global ALL_TEXTURE_FILES
    ALL_TEXTURE_FILES = []
    for root, _, files in os.walk(TEXTURE_FOLDER_PATH):
        for file in files:
            if file.lower().endswith(".png"):
                file_path = os.path.join(root, file)
                file_name = os.path.splitext(file)[0]
                ALL_TEXTURE_FILES.append({"name":file_name,"path":file_path,"lower_name":file_name.lower()})

def find_texture_path(block_name):
    clean_name = block_name
    original_shape, _, _ = get_base_shape(block_name)
    if original_shape in clean_name:
        clean_name = clean_name.replace(original_shape, "").strip()
    for tex in ALL_TEXTURE_FILES:
        if tex["name"] == block_name: return tex["path"]
    for tex in ALL_TEXTURE_FILES:
        if tex["name"] == clean_name: return tex["path"]
    keywords = []
    if len(clean_name) >= 3: keywords.append(clean_name[:3])
    keywords.append(clean_name)
    keywords.append(block_name)
    lower_clean = clean_name.lower()
    lower_block = block_name.lower()
    for tex in ALL_TEXTURE_FILES:
        for kw in keywords:
            if kw == tex["name"]: return tex["path"]
    for tex in ALL_TEXTURE_FILES:
        if lower_clean and lower_clean in tex["lower_name"]: return tex["path"]
        if lower_block in tex["lower_name"]: return tex["path"]
    return None

def get_or_create_material(block_name):
    material_name = f"MI_{block_name}"
    if material_name in MATERIAL_CACHE: return MATERIAL_CACHE[material_name]
    texture_path = find_texture_path(block_name)
    mat = bpy.data.materials.new(name=material_name)
    mat.use_nodes = True
    mat.blend_method = 'CLIP'
    mat.shadow_method = 'CLIP'
    nodes = mat.node_tree.nodes
    links = mat.node_tree.links
    for node in nodes: nodes.remove(node)
    node_uv = nodes.new(type='ShaderNodeUVMap')
    node_mapping = nodes.new(type='ShaderNodeMapping')
    node_tex = nodes.new(type='ShaderNodeTexImage')
    node_bsdf = nodes.new(type='ShaderNodeBsdfPrincipled')
    node_output = nodes.new(type='ShaderNodeOutputMaterial')
    node_uv.location = (-1200, 0)
    node_mapping.location = (-900, 0)
    node_tex.location = (-600, 0)
    node_bsdf.location = (-200, 0)
    node_output.location = (200, 0)
    node_bsdf.inputs['Roughness'].default_value = 0.8
    node_bsdf.inputs['Specular'].default_value = 0.1
    node_bsdf.inputs['Alpha'].default_value = 1.0
    texture_loaded = False
    if texture_path:
        try:
            img = bpy.data.images.load(texture_path)
            img.colorspace_settings.name = 'sRGB'
            node_tex.image = img
            texture_loaded = True
        except:
            pass
    links.new(node_uv.outputs['UV'], node_mapping.inputs['Vector'])
    links.new(node_mapping.outputs['Vector'], node_tex.inputs['Vector'])
    links.new(node_tex.outputs['Color'], node_bsdf.inputs['Base Color'])
    if texture_loaded:
        links.new(node_tex.outputs['Alpha'], node_bsdf.inputs['Alpha'])
    links.new(node_bsdf.outputs['BSDF'], node_output.inputs['Surface'])
    MATERIAL_CACHE[material_name] = mat
    return mat

# ===================== 通用 BMesh 优化 =====================
def optimize_bmesh(bm: bmesh.types.BMesh, is_cube: bool = False):
    if ENABLE_BASIC_CLEANUP:
        bmesh.ops.delete(bm, geom=[v for v in bm.verts if not v.link_faces], context='VERTS')
    if ENABLE_VERTEX_WELD and is_cube:
        bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=WELD_THRESHOLD)
    bm.normal_update()
    return bm

# ===================== 贪婪网格化算法 =====================
def greedy_quads_2d(exposed, a_min, a_max, b_min, b_max):
    """二维扫描线矩形合并算法，返回矩形列表 (a_start, a_end, b_start, b_end)"""
    width = a_max - a_min + 1
    if width <= 0 or (b_max - b_min + 1) <= 0:
        return []
    height = b_max - b_min + 1
    visited = [[False] * width for _ in range(height)]

    for (a, b) in exposed:
        if a_min <= a <= a_max and b_min <= b <= b_max:
            visited[b - b_min][a - a_min] = True

    quads = []
    for j in range(height):
        for i in range(width):
            if not visited[j][i]:
                continue
            # 向右扩展
            w = i
            while w + 1 < width and visited[j][w + 1]:
                w += 1
            rect_w = w - i + 1

            # 向下扩展
            h = j
            while h + 1 < height:
                full_row = True
                for k in range(i, i + rect_w):
                    if not visited[h + 1][k]:
                        full_row = False
                        break
                if not full_row:
                    break
                h += 1
            rect_h = h - j + 1

            # 标记已访问
            for y in range(j, j + rect_h):
                for x in range(i, i + rect_w):
                    visited[y][x] = False

            quads.append((a_min + i, a_min + i + rect_w - 1, b_min + j, b_min + j + rect_h - 1))
    return quads

def greedy_mesh_from_blocks(block_positions_blender, face_material_callback):
    """
    在 Blender 坐标系下生成贪婪网格化 BMesh
    block_positions_blender: set of (x, y, z) 整数坐标（已变换）
    face_material_callback: function(normal_vec) -> material_index
    """
    bm = bmesh.new()
    uv_layer = bm.loops.layers.uv.verify()

    # 六个方向：nx, ny, nz
    directions = [
        ('+X', (1, 0, 0)),
        ('-X', (-1, 0, 0)),
        ('+Y', (0, 1, 0)),
        ('-Y', (0, -1, 0)),
        ('+Z', (0, 0, 1)),
        ('-Z', (0, 0, -1))
    ]

    for dir_name, normal in directions:
        nx, ny, nz = normal
        mat_idx = face_material_callback(normal)

        # 判断方块是否暴露于该方向
        def is_exposed(pos):
            neighbor = (pos[0] + nx, pos[1] + ny, pos[2] + nz)
            return neighbor not in block_positions_blender

        # 确定该方向的轴坐标，以及另外两个轴
        if nx != 0:
            axis_idx = 0
            u_idx, v_idx = 1, 2  # Y, Z
        elif ny != 0:
            axis_idx = 1
            u_idx, v_idx = 0, 2  # X, Z
        else:  # nz
            axis_idx = 2
            u_idx, v_idx = 0, 1  # X, Y

        # 收集暴露方块，并按层分组 (layer_coord -> {(u, v)})
        layers = defaultdict(set)
        for pos in block_positions_blender:
            if is_exposed(pos):
                layer_coord = pos[axis_idx]
                layers[layer_coord].add((pos[u_idx], pos[v_idx]))

        # 对每一层执行二维矩形合并
        for layer_coord, uv_set in layers.items():
            if not uv_set:
                continue

            u_vals = [p[0] for p in uv_set]
            v_vals = [p[1] for p in uv_set]
            u_min, u_max = min(u_vals), max(u_vals)
            v_min, v_max = min(v_vals), max(v_vals)

            quads = greedy_quads_2d(uv_set, u_min, u_max, v_min, v_max)

            for (u_start, u_end, v_start, v_end) in quads:
                # 矩形在 u, v 方向跨越的方块数
                u_range = u_end - u_start + 1
                v_range = v_end - v_start + 1

                # 根据方向生成顶点坐标（Blender 空间）及 UV
                if dir_name == '+X':
                    x = layer_coord + 0.5
                    v0 = (x, u_start - 0.5, v_start - 0.5)
                    v1 = (x, u_end + 0.5, v_start - 0.5)
                    v2 = (x, u_end + 0.5, v_end + 0.5)
                    v3 = (x, u_start - 0.5, v_end + 0.5)
                    # UV: u=1-z, v=y -> 以矩形最小值为基准
                    uv0 = (0, 0)
                    uv1 = (u_range, 0)
                    uv2 = (u_range, v_range)
                    uv3 = (0, v_range)
                    verts = [v0, v1, v2, v3]
                    uvs = [uv0, uv1, uv2, uv3]

                elif dir_name == '-X':
                    x = layer_coord - 0.5
                    v0 = (x, u_start - 0.5, v_start - 0.5)
                    v1 = (x, u_end + 0.5, v_start - 0.5)
                    v2 = (x, u_end + 0.5, v_end + 0.5)
                    v3 = (x, u_start - 0.5, v_end + 0.5)
                    # UV: u=z, v=y -> 顺时针顺序确保法线向外
                    uv0 = (0, 0)
                    uv1 = (u_range, 0)
                    uv2 = (u_range, v_range)
                    uv3 = (0, v_range)
                    verts = [v0, v3, v2, v1]
                    uvs = [uv0, uv3, uv2, uv1]

                elif dir_name == '+Y':
                    y = layer_coord + 0.5
                    v0 = (u_start - 0.5, y, v_start - 0.5)
                    v1 = (u_end + 0.5, y, v_start - 0.5)
                    v2 = (u_end + 0.5, y, v_end + 0.5)
                    v3 = (u_start - 0.5, y, v_end + 0.5)
                    # UV: u=x, v=z
                    uv0 = (0, 0)
                    uv1 = (u_range, 0)
                    uv2 = (u_range, v_range)
                    uv3 = (0, v_range)
                    verts = [v0, v1, v2, v3]
                    uvs = [uv0, uv1, uv2, uv3]

                elif dir_name == '-Y':
                    y = layer_coord - 0.5
                    v0 = (u_start - 0.5, y, v_start - 0.5)
                    v1 = (u_end + 0.5, y, v_start - 0.5)
                    v2 = (u_end + 0.5, y, v_end + 0.5)
                    v3 = (u_start - 0.5, y, v_end + 0.5)
                    # UV: u=1-x, v=z -> 使用世界坐标映射，保持纹理方向
                    uv0 = (u_range, 0)
                    uv1 = (0, 0)
                    uv2 = (0, v_range)
                    uv3 = (u_range, v_range)
                    verts = [v1, v0, v3, v2]
                    uvs = [uv1, uv0, uv3, uv2]

                elif dir_name == '+Z':
                    z = layer_coord + 0.5
                    v0 = (u_start - 0.5, v_start - 0.5, z)
                    v1 = (u_end + 0.5, v_start - 0.5, z)
                    v2 = (u_end + 0.5, v_end + 0.5, z)
                    v3 = (u_start - 0.5, v_end + 0.5, z)
                    # UV: u=x, v=1-y -> v 翻转
                    uv0 = (0, v_range)
                    uv1 = (u_range, v_range)
                    uv2 = (u_range, 0)
                    uv3 = (0, 0)
                    verts = [v0, v1, v2, v3]
                    uvs = [uv0, uv1, uv2, uv3]

                elif dir_name == '-Z':
                    z = layer_coord - 0.5
                    v0 = (u_start - 0.5, v_start - 0.5, z)
                    v1 = (u_end + 0.5, v_start - 0.5, z)
                    v2 = (u_end + 0.5, v_end + 0.5, z)
                    v3 = (u_start - 0.5, v_end + 0.5, z)
                    # UV: u=x, v=y
                    uv0 = (0, 0)
                    uv1 = (u_range, 0)
                    uv2 = (u_range, v_range)
                    uv3 = (0, v_range)
                    verts = [v1, v0, v3, v2]
                    uvs = [uv1, uv0, uv3, uv2]

                # 创建四边面
                bm_verts = [bm.verts.new(v) for v in verts]
                face = bm.faces.new(bm_verts)
                face.material_index = mat_idx
                for loop, uv in zip(face.loops, uvs):
                    loop[uv_layer].uv = uv

    return bm

# ===================== 合并与生成入口 =====================
def merge_meshes_by_material(material_block_groups):
    total_merged = 0
    mat_top, mat_side, mat_bottom = get_grass_block_materials()

    for group_key, block_list in material_block_groups.items():
        if not block_list:
            continue
        group_type = group_key[0]
        print(f"\n🔨 开始处理 {group_type} 组，共 {len(block_list)} 个方块")

        # ---------- 长草土块（标准立方体，贪婪网格化）----------
        if group_type == "grass_block":
            pos_set = set()
            for block_data in block_list:
                x, y, z, *_ = block_data
                bx, by, bz = C_MATRIX @ Vector((x, y, z))
                pos_set.add((int(bx), int(by), int(bz)))

            def grass_face_mat(normal):
                if normal[2] > 0.99:      # Blender +Z → 顶面
                    return 0
                elif normal[2] < -0.99:    # Blender -Z → 底面
                    return 2
                else:
                    return 1

            bm = greedy_mesh_from_blocks(pos_set, grass_face_mat)
            bm = optimize_bmesh(bm, is_cube=True)
            msh = bpy.data.meshes.new("merged_grass_block")
            bm.to_mesh(msh)
            bm.free()
            while len(msh.materials) < 3:
                msh.materials.append(None)
            obj = bpy.data.objects.new("OBJ_长草土块合集", msh)
            bpy.context.collection.objects.link(obj)
            obj.data.materials[0] = mat_top
            obj.data.materials[1] = mat_side
            obj.data.materials[2] = mat_bottom
            total_merged += len(pos_set)
            print(f"✅ 草方块组贪婪网格化完成，方块数 {len(pos_set)}，面数 {len(msh.polygons)}")
            continue

        # ---------- 特殊模型（保持原逻辑）----------
        if group_type == "special":
            obj_filename = group_key[1]
            mesh_data = load_special_mesh(obj_filename)
            if not mesh_data: continue
            mat = get_or_create_special_material(obj_filename)
            merged_bm = bmesh.new()
            uv_layer = merged_bm.loops.layers.uv.verify()
            success_block = 0
            for block_data in block_list:
                try:
                    x, y, z, *rest = block_data
                    world_pos = C_MATRIX @ Vector((x, y, z))
                    world_mat = Matrix.Translation(world_pos)
                    temp_bm = bmesh.new()
                    temp_bm.from_mesh(mesh_data)
                    temp_bm.transform(world_mat)
                    vert_map = {v: merged_bm.verts.new(v.co) for v in temp_bm.verts}
                    for f in temp_bm.faces:
                        nf = merged_bm.faces.new([vert_map[v] for v in f.verts])
                        for l, nl in zip(f.loops, nf.loops):
                            nl[uv_layer].uv = l[temp_bm.loops.layers.uv.active].uv
                        nf.material_index = 0
                    temp_bm.free()
                    success_block += 1
                except Exception as e:
                    print(f"⚠️ 特殊模型处理失败 {block_data}: {str(e)}")
                    continue
            if success_block > 0:
                merged_bm = optimize_bmesh(merged_bm, is_cube=False)
                msh = bpy.data.meshes.new(f"merged_special_{obj_filename.replace('.obj','')}")
                merged_bm.to_mesh(msh)
                merged_bm.free()
                obj = bpy.data.objects.new(f"OBJ_special_{obj_filename.replace('.obj','')}", msh)
                bpy.context.collection.objects.link(obj)
                obj.data.materials.append(mat)
                total_merged += success_block
                print(f"✅ 特殊模型组处理完成，成功 {success_block} 个")
            continue

        # ---------- 普通立方体 / 彩色立方体（贪婪网格化）----------
        # 判定：普通且为立方体，或纯色块（均为标准立方体）
        is_standard_cube = False
        if group_type == "normal":
            _, base_shape, _ = get_base_shape(group_key[1])
            if base_shape == "立方体":
                is_standard_cube = True
                mat = get_or_create_material(group_key[1])
                pos_set = set()
                for block_data in block_list:
                    x, y, z, data, name = block_data
                    t_idx, d_idx, upside = parse_data_value("立方体", data)
                    # 注意：这里需要使用旋转矩阵，但贪婪网格化目前仅处理统一的轴对齐方块。
                    # 如果立方体有旋转（方向/翻转），则不能简单地用 axis-aligned 合并。
                    if d_idx != 0 or upside:
                        is_standard_cube = False   # 非默认旋转，使用老方法
                        break
                    # 否则仅平移
                    blender_pos = C_MATRIX @ Vector((x, y, z))
                    pos_set.add((int(blender_pos.x), int(blender_pos.y), int(blender_pos.z)))
                if is_standard_cube:
                    bm = greedy_mesh_from_blocks(pos_set, lambda n: 0)
                    bm = optimize_bmesh(bm, is_cube=True)
                    msh = bpy.data.meshes.new(f"merged_normal_cube_{group_key[1]}")
                    bm.to_mesh(msh)
                    bm.free()
                    obj = bpy.data.objects.new(f"OBJ_{group_key[1]}", msh)
                    bpy.context.collection.objects.link(obj)
                    obj.data.materials.append(mat)
                    total_merged += len(pos_set)
                    print(f"✅ 普通立方体贪婪网格化完成，方块数 {len(pos_set)}，面数 {len(msh.polygons)}")
                    continue
            # 如果不是立方体，继续执行下方旧逻辑（楼梯、斜坡等）

        elif group_type in ("glass", "cotton", "concrete"):
            # 纯色立方体，通常无旋转，直接贪婪合并
            pos_set = set()
            for block_data in block_list:
                x, y, z, *_ = block_data
                blender_pos = C_MATRIX @ Vector((x, y, z))
                pos_set.add((int(blender_pos.x), int(blender_pos.y), int(blender_pos.z)))
            mat = get_or_create_color_material(*group_key)
            bm = greedy_mesh_from_blocks(pos_set, lambda n: 0)
            bm = optimize_bmesh(bm, is_cube=True)
            msh = bpy.data.meshes.new(f"merged_{group_type}_{group_key[1]}_{group_key[2]}")
            bm.to_mesh(msh)
            bm.free()
            obj = bpy.data.objects.new(f"OBJ_{group_key}", msh)
            bpy.context.collection.objects.link(obj)
            obj.data.materials.append(mat)
            total_merged += len(pos_set)
            print(f"✅ 纯色立方体贪婪网格化完成，方块数 {len(pos_set)}，面数 {len(msh.polygons)}")
            continue

        # ---------- 非标准立方体旧逻辑（楼梯、斜板等）----------
        merged_bm = bmesh.new()
        uv_layer = merged_bm.loops.layers.uv.verify()
        success_block = 0
        if group_type == "normal":
            mat = get_or_create_material(group_key[1])
        else:
            # 不应该走到这里，但兜底
            mat = get_or_create_color_material(*group_key)

        for block_data in block_list:
            try:
                x, y, z, data, name = block_data
                original_shape, base_shape, is_large = get_base_shape(name)
                t_idx, d_idx, upside = parse_data_value(base_shape, data)
                obj_fn = generate_obj_filename(original_shape, t_idx)
                mesh_data = load_obj_mesh(obj_fn)
                if not mesh_data:
                    continue
                world_mat = calculate_world_matrix(x, y, z, d_idx, upside)
                temp_bm = bmesh.new()
                temp_bm.from_mesh(mesh_data)
                temp_bm.transform(world_mat)
                vert_map = {v: merged_bm.verts.new(v.co) for v in temp_bm.verts}
                for f in temp_bm.faces:
                    nf = merged_bm.faces.new([vert_map[v] for v in f.verts])
                    for l, nl in zip(f.loops, nf.loops):
                        nl[uv_layer].uv = l[temp_bm.loops.layers.uv.active].uv
                    nf.material_index = 0
                temp_bm.free()
                success_block += 1
            except Exception as e:
                print(f"⚠️ 自定义模型处理失败 {block_data}: {str(e)}")
                continue

        if success_block > 0:
            merged_bm = optimize_bmesh(merged_bm, is_cube=False)
            msh = bpy.data.meshes.new(f"merged_{group_key}")
            merged_bm.to_mesh(msh)
            merged_bm.free()
            obj = bpy.data.objects.new(f"OBJ_{group_key}", msh)
            bpy.context.collection.objects.link(obj)
            obj.data.materials.append(mat)
            total_merged += success_block
            print(f"✅ 自定义形状组处理完成，成功 {success_block} 个")

    return total_merged

# ===================== 核心构建函数 =====================
def build_model_from_csv(csv_filepath, root_path, clean_scene):
    global ROOT_PATH, CSV_FILE_PATH, OBJ_FOLDER_PATH, TEXTURE_FOLDER_PATH
    global COLOR_MAP_PATH, SPECIAL_OBJ_FOLDER, SPECIAL_DICT_PATH
    global GRASS_TOP_PATH, GRASS_SIDE_PATH, GRASS_BOTTOM_PATH
    
    # 重置全局缓存
    reset_global_caches()
    
    # 设置全局路径
    ROOT_PATH = root_path
    CSV_FILE_PATH = csv_filepath
    OBJ_FOLDER_PATH = os.path.join(ROOT_PATH, "blocks_obj")
    TEXTURE_FOLDER_PATH = os.path.join(ROOT_PATH, "blocks_texture")
    COLOR_MAP_PATH = os.path.join(ROOT_PATH, "color_map")
    SPECIAL_OBJ_FOLDER = os.path.join(ROOT_PATH, "specai_obj")
    SPECIAL_DICT_PATH = os.path.join(SPECIAL_OBJ_FOLDER, "obj_dict.txt")
    GRASS_TOP_PATH = os.path.join(TEXTURE_FOLDER_PATH, GRASS_TOP_NAME)
    GRASS_SIDE_PATH = os.path.join(TEXTURE_FOLDER_PATH, GRASS_SIDE_NAME)
    GRASS_BOTTOM_PATH = os.path.join(TEXTURE_FOLDER_PATH, GRASS_BOTTOM_NAME)
    
    # 清理场景选项
    if clean_scene:
        bpy.ops.object.select_all(action='SELECT')
        bpy.ops.object.delete(use_global=False)
        # 清理未使用的数据块
        for mesh in bpy.data.meshes:
            if not mesh.users:
                bpy.data.meshes.remove(mesh)
        for mat in bpy.data.materials:
            if not mat.users:
                bpy.data.materials.remove(mat)
        for img in bpy.data.images:
            if not img.users:
                bpy.data.images.remove(img)
    
    # 加载必要资源
    load_color_maps()
    preload_all_textures()
    load_special_obj_dict()
    
    if not os.path.exists(CSV_FILE_PATH):
        raise FileNotFoundError(f"CSV文件不存在: {CSV_FILE_PATH}")
    
    print(f"\n📖 正在扫描CSV文件...")
    material_block_groups = defaultdict(list)
    total_rows = error_rows = 0
    
    with open(CSV_FILE_PATH, 'r', encoding='utf-8-sig') as f:
        reader = csv.DictReader(f)
        has_id = 'id' in reader.fieldnames
        for row in reader:
            total_rows += 1
            try:
                x = float(row['x']); y = float(row['y']); z = float(row['z'])
                data = int(row['data']); name = row['name'].strip()
                btype = get_block_type(name)
                
                if btype == "special":
                    obj_filename = OBJ_DICT.get(name + ".obj")
                    if not obj_filename:
                        error_rows += 1
                        continue
                    material_block_groups[("special", obj_filename)].append((x, y, z, data, name))
                elif btype == "grass_block":
                    material_block_groups[("grass_block",)].append((x, y, z, data, name))
                elif btype == "normal":
                    material_block_groups[("normal", name)].append((x, y, z, data, name))
                else:
                    if not has_id:
                        error_rows += 1
                        continue
                    bid = int(row['id'])
                    material_block_groups[(btype, bid, data)].append((x, y, z, data, name, bid, btype))
            except Exception as e:
                error_rows += 1
                print(f"⚠️ CSV行解析失败 行号{total_rows}: {str(e)}")
    
    print(f"✅ CSV扫描完成，发现 {len(material_block_groups)} 类不同方块，总计 {total_rows} 行数据")
    
    total_merged = merge_meshes_by_material(material_block_groups)
    
    # 清理未使用的数据块
    for mesh in bpy.data.meshes:
        if not mesh.users: bpy.data.meshes.remove(mesh)
    for mat in bpy.data.materials:
        if not mat.users: bpy.data.materials.remove(mat)
    for img in bpy.data.images:
        if not img.users: bpy.data.images.remove(img)
    
    total_verts = 0
    total_faces = 0
    for obj in bpy.context.collection.objects:
        if obj.type == 'MESH':
            total_verts += len(obj.data.vertices)
            total_faces += len(obj.data.polygons)
    
    print("\n" + "="*60)
    print(f"🎉 全部处理完成！")
    print(f"📊 原始数据：{total_rows} 行 | 成功生成：{total_merged} 个方块 | 失败：{error_rows} 个")
    print(f"💾 最终场景：总顶点数 {total_verts} | 总面数 {total_faces}")
    print("="*60)
    
    return total_merged, total_rows, error_rows

# ===================== 插件UI和运算符 =====================
class Mini2BlenderProperties(bpy.types.PropertyGroup):
    root_directory: bpy.props.StringProperty(
        name="项目根目录",
        description="包含csv、blocks_obj、blocks_texture等文件夹的根目录",
        subtype='DIR_PATH',
        default=""
    )
    csv_file_path: bpy.props.StringProperty(
        name="CSV文件路径",
        description="手动指定CSV文件（如果留空，将使用根目录/csv/blocks.csv）",
        subtype='FILE_PATH',
        default=""
    )
    clean_scene: bpy.props.BoolProperty(
        name="清空场景",
        description="生成模型前清空当前场景所有物体",
        default=True
    )

class MINI2BLENDER_OT_import(bpy.types.Operator):
    bl_idname = "mini2blender.import"
    bl_label = "生成模型"
    bl_description = "根据CSV数据生成方块模型"
    bl_options = {'REGISTER', 'UNDO'}
    
    def execute(self, context):
        props = context.scene.mini2blender_props
        
        # 确定CSV文件路径
        csv_path = props.csv_file_path.strip()
        root_path = props.root_directory.strip()
        
        if not root_path:
            self.report({'ERROR'}, "请先设置项目根目录")
            return {'CANCELLED'}
        
        if not os.path.isdir(root_path):
            self.report({'ERROR'}, f"根目录不存在: {root_path}")
            return {'CANCELLED'}
        
        # 如果没有手动指定CSV，使用默认路径
        if not csv_path:
            default_csv = os.path.join(root_path, "csv", "blocks.csv")
            if os.path.exists(default_csv):
                csv_path = default_csv
            else:
                self.report({'ERROR'}, f"未找到默认CSV文件: {default_csv}\n请手动选择CSV文件或确保目录结构正确")
                return {'CANCELLED'}
        elif not os.path.exists(csv_path):
            self.report({'ERROR'}, f"CSV文件不存在: {csv_path}")
            return {'CANCELLED'}
        
        # 可选：检查必要的子文件夹是否存在
        required_dirs = ["blocks_obj", "blocks_texture", "color_map", "specai_obj"]
        missing_dirs = [d for d in required_dirs if not os.path.isdir(os.path.join(root_path, d))]
        if missing_dirs:
            self.report({'WARNING'}, f"缺少以下资源文件夹: {', '.join(missing_dirs)}，可能影响模型生成")
        
        try:
            # 记录开始时间
            import time
            start_time = time.time()
            
            # 切换到对象模式
            if bpy.ops.object.mode_set.poll():
                bpy.ops.object.mode_set(mode='OBJECT')
            
            total_merged, total_rows, error_rows = build_model_from_csv(
                csv_path, root_path, props.clean_scene
            )
            
            elapsed = time.time() - start_time
            self.report({'INFO'}, f"生成完成 | 方块: {total_merged}/{total_rows} | 耗时: {elapsed:.2f}秒 | 错误: {error_rows}")
            
            if error_rows > 0:
                self.report({'WARNING'}, f"有 {error_rows} 个方块未能成功生成，请查看控制台输出")
            
        except Exception as e:
            self.report({'ERROR'}, f"生成失败: {str(e)}")
            import traceback
            traceback.print_exc()
            return {'CANCELLED'}
        
        return {'FINISHED'}

class MINI2BLENDER_PT_panel(bpy.types.Panel):
    bl_label = "Mini2Blender 导入器"
    bl_idname = "MINI2BLENDER_PT_panel"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "Mini2Blender"
    
    def draw(self, context):
        layout = self.layout
        props = context.scene.mini2blender_props
        
        box = layout.box()
        box.label(text="路径设置", icon='FILE_FOLDER')
        box.prop(props, "root_directory")
        box.prop(props, "csv_file_path")
        
        box = layout.box()
        box.label(text="选项", icon='SETTINGS')
        box.prop(props, "clean_scene")
        
        layout.separator()
        layout.operator("mini2blender.import", icon='IMPORT', text="开始生成模型")
        
# ===================== 注册插件 =====================
classes = [
    Mini2BlenderProperties,
    MINI2BLENDER_OT_import,
    MINI2BLENDER_PT_panel,
]

def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    bpy.types.Scene.mini2blender_props = bpy.props.PointerProperty(type=Mini2BlenderProperties)

def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
    del bpy.types.Scene.mini2blender_props

if __name__ == "__main__":
    register()