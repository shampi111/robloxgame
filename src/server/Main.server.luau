-- Точка входа сервера.
local Lighting = game:GetService("Lighting")
local PhysicsService = game:GetService("PhysicsService")

local GameLoop = require(script.Parent.GameLoop)
local MapBuilder = require(script.Parent.MapBuilder)
local PlayerData = require(script.Parent.PlayerData)
local Textures = require(script.Parent.Textures)

-- Atmosphere отключает туман Lighting.FogEnd, на котором держится вся темнота
-- (например, Atmosphere есть в шаблоне Baseplate) — убираем её.
for _, child in Lighting:GetChildren() do
	if child:IsA("Atmosphere") then
		child:Destroy()
	end
end

-- Монстр подвала сталкивается с барьером у выхода, игроки — нет.
PhysicsService:RegisterCollisionGroup("Monster")
PhysicsService:RegisterCollisionGroup("MonsterBarrier")
PhysicsService:CollisionGroupSetCollidable("MonsterBarrier", "Default", false)

Textures.preload()
MapBuilder.buildLobby()
PlayerData.start()
GameLoop.start()
