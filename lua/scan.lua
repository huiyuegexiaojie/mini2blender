-- 适配版：保留原版逻辑 + 玩家移动分区块采集 + 聊天栏进度显示
-- 核心：不改动原版输出/去重/格式，仅新增区块拆分+玩家移动+聊天栏进度
-- 触发方式：1.游戏启动自动执行 2.玩家点击方块触发
-- ===================== 1. 全局配置（完全保留原版，新增区块配置） =====================
local CONFIG = {
    -- 原版坐标配置（你可自定义修改）
    POS1 = {x = 4, y = 7, z = 37},
    POS2 = {x = 65, y = 64, z = -34},
    -- 新增区块采集配置（关键适配）
    BLOCK_SIZE = 32,          -- 32×32×32区块拆分
    PLAYER_OFFSET_Y = 7,      -- 玩家移动到区块顶部+7格
    -- 原版输出配置（完全保留）
    SEGMENT_THRESHOLD = 150,
    EMPTY_BLOCK_ID = 0,
    CSV_HEADER = "方块X坐标,方块Y坐标,方块Z坐标,方块ID,方块附加Data,方块名称"
}
-- ===================== 2. 基础工具函数（完全保留原版） =====================
local function getBlockId(x, y, z)
    local ret, id = Block:getBlockID(x, y, z)
    return ret == ErrorCode.OK and id or CONFIG.EMPTY_BLOCK_ID
end
local function getBlockData(x, y, z)
    local ret, data = Block:getBlockData(x, y, z)
    return ret == ErrorCode.OK and data or 0
end
local function getBlockName(blockId)
    local ret, name = Block:GetBlockDefName(blockId)
    local safeName = ret == ErrorCode.OK and name or "未知方块"
    return string.gsub(safeName, ",", "，")
end
local function formatCsvLine(x, y, z, blockId, blockData, blockName)
    return string.format("%d,%d,%d,%d,%d,%s", x, y, z, blockId, blockData, blockName)
end
local function printSegmentLog(segment, isLast, csvLines)
    local segTitle = isLast and string.format("数据分段%d（最后一段）", segment) 
                             or string.format("数据分段%d", segment)
    print("===== " .. segTitle .. " =====")
    print(table.concat(csvLines, "\n"))
    print("=====================")
end
-- ===================== 新增：聊天栏发送消息函数 =====================
local function sendChatMsg(playerId, msg)
    pcall(function()
        Chat:sendSystemMsg(msg, playerId)
    end)
end

-- ===================== 3. 新增：玩家移动/区块拆分核心函数（适配关键） =====================
-- 锁定/解锁玩家移动
local function lockPlayerMove(playerId, isLock)
    pcall(function()
        Player:changPlayerMoveType(playerId, isLock and 1 or 2)
        print(isLock and "[采集] 🔒 锁定玩家移动" or "[采集] 🔓 解锁玩家移动")
    end)
end
-- 移动玩家到区块上方+延迟加载（确保区块加载完成）
local function movePlayerToBlock(playerId, block)
    local targetX = math.floor((block.x1 + block.x2) / 2)
    local targetY = block.y2 + CONFIG.PLAYER_OFFSET_Y
    local targetZ = math.floor((block.z1 + block.z2) / 2)
    
    pcall(function()
        Player:setPosition(playerId, targetX, targetY, targetZ)
        print(string.format("[采集] 📌 玩家已移动到区块%d上方：X=%d Y=%d Z=%d",
            block.idx, targetX, targetY, targetZ))
    end)
    pcall(function() threadpool:wait(0.5) end)
end
-- 拆分32×32×32区块
local function splitTo32Blocks()
    local p1, p2 = CONFIG.POS1, CONFIG.POS2
    local area = {
        x1 = math.min(p1.x, p2.x), x2 = math.max(p1.x, p2.x),
        y1 = math.min(p1.y, p2.y), y2 = math.max(p1.y, p2.y),
        z1 = math.min(p1.z, p2.z), z2 = math.max(p1.z, p2.z)
    }
    print(string.format("[采集] 📏 扫描区域：X(%d~%d) Y(%d~%d) Z(%d~%d)",
        area.x1, area.x2, area.y1, area.y2, area.z1, area.z2))
    
    local blocks = {}
    local bs = CONFIG.BLOCK_SIZE
    for xIdx = 0, math.ceil((area.x2 - area.x1) / bs) - 1 do
        for yIdx = 0, math.ceil((area.y2 - area.y1) / bs) - 1 do
            for zIdx = 0, math.ceil((area.z2 - area.z1) / bs) - 1 do
                local x1 = area.x1 + xIdx * bs
                local x2 = math.min(x1 + bs - 1, area.x2)
                local y1 = area.y1 + yIdx * bs
                local y2 = math.min(y1 + bs - 1, area.y2)
                local z1 = area.z1 + zIdx * bs
                local z2 = math.min(z1 + bs - 1, area.z2)
                table.insert(blocks, {
                    idx = #blocks + 1,
                    x1 = x1, x2 = x2, y1 = y1, y2 = y2, z1 = z1, z2 = z2
                })
            end
        end
    end
    print(string.format("[采集] ✅ 拆分完成：共%d个32×32×32区块", #blocks))
    return blocks
end
-- ===================== 4. 采集函数 =====================
local function collectBlockData(playerId, block)
    local csvLines = {CONFIG.CSV_HEADER}
    local blockUniqueMap = {}
    local count = 0
    local segment = 1
    local x1,x2,y1,y2,z1,z2 = block.x1,block.x2,block.y1,block.y2,block.z1,block.z2
    
    for x = x1, x2 do
        for y = y1, y2 do
            for z = z1, z2 do
                local blockId = getBlockId(x, y, z)
                if blockId ~= CONFIG.EMPTY_BLOCK_ID then
                    local uniqueKey = (x * 1000000) + (y * 1000) + z + (blockId * 1000000000)
                    if not blockUniqueMap[uniqueKey] then
                        local blockData = getBlockData(x, y, z)
                        local blockName = getBlockName(blockId)
                        table.insert(csvLines, formatCsvLine(x, y, z, blockId, blockData, blockName))
                        count = count + 1
                        blockUniqueMap[uniqueKey] = true
                        
                        if #csvLines >= CONFIG.SEGMENT_THRESHOLD then
                            printSegmentLog(segment, false, csvLines)
                            csvLines = {CONFIG.CSV_HEADER}
                            segment = segment + 1
                        end
                    end
                end
            end
        end
    end
    
    if #csvLines > 1 then
        printSegmentLog(segment, true, csvLines)
    end
    print(string.format("[采集] ✅ 区块%d完成：共%d个唯一方块", block.idx, count))
    return count
end
-- ===================== 5. 主函数（带聊天进度） =====================
local function mainCollect(playerId)
    print("[采集] ===== 🚀 原版脚本+分区块采集启动 =====")
    sendChatMsg(playerId, "[方块采集] 🔄 开始采集区域方块数据...")
    lockPlayerMove(playerId, true)
    
    local blocks = splitTo32Blocks()
    if #blocks == 0 then
        print("[采集] ❌ 无有效区块，请检查坐标！")
        sendChatMsg(playerId, "[方块采集] ❌ 无有效区块")
        lockPlayerMove(playerId, false)
        return
    end
    
    sendChatMsg(playerId, string.format("[方块采集] 📦 总区块：%d个", #blocks))
    local totalCount = 0
    
    for i, block in ipairs(blocks) do
        local pct = math.floor((i / #blocks) * 100)
        sendChatMsg(playerId, string.format("[方块采集] 📍 第%d/%d区块 进度%d%%", i, #blocks, pct))
        movePlayerToBlock(playerId, block)
        local cnt = collectBlockData(playerId, block)
        totalCount = totalCount + cnt
        sendChatMsg(playerId, string.format("[方块采集] ✅ 区块%d完成 累计：%d", block.idx, totalCount))
    end
    
    lockPlayerMove(playerId, false)
    print("[采集] ===== 🎯 全区域采集完成 ======")
    print(string.format("[采集] 📈 总计：%d个唯一方块", totalCount))
    
    sendChatMsg(playerId, string.format("[方块采集] 🎉 全部完成！共%d个方块", totalCount))
    sendChatMsg(playerId, "[方块采集] 💡 复制日志可Excel整理")
end
-- ===================== 6. 触发事件 =====================
ScriptSupportEvent:registerEvent("Player.ClickBlock", function(e)
    local playerId = e.eventobjid
    local x, y, z = e.x, e.y, e.z
    local blockId = getBlockId(x, y, z)
    local blockName = getBlockName(blockId)
    if blockId == CONFIG.EMPTY_BLOCK_ID then
        print(string.format("[采集] 📌 点击位置：X=%d Y=%d Z=%d（空气）", x, y, z))
    else
        print(string.format("[采集] 📌 点击方块：X=%d Y=%d Z=%d ID=%d %s", x, y, z, blockId, blockName))
    end
    mainCollect(playerId)
end)

ScriptSupportEvent:registerEvent("Game.Start", function()
    pcall(function()
        local players = Player:getAllPlayers()
        if #players > 0 then
            mainCollect(players[1])
        else
            print("[采集] ❌ 启动时无玩家")
        end
    end)
end)

print("[采集] ✅ 脚本+聊天进度已加载！")