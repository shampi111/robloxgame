-- Статистика игроков (leaderstats) с сохранением в DataStore.
-- В Studio без доступа к API прогресс просто не сохраняется, игра при этом работает.
local DataStoreService = game:GetService("DataStoreService")
local Players = game:GetService("Players")
local ReplicatedStorage = game:GetService("ReplicatedStorage")
local RunService = game:GetService("RunService")

local Config = require(ReplicatedStorage.Shared.Config)

local PlayerData = {}

local profiles = {} -- [Player] = { values = { [key] = IntValue }, canSave = boolean }
local activeSaves = 0

local store
do
	local ok, result = pcall(DataStoreService.GetDataStore, DataStoreService, Config.DataStoreName)
	if ok then
		store = result
	else
		warn(
			"[PlayerData] DataStore недоступен, прогресс не будет сохраняться:",
			result
		)
	end
end

local function keyFor(player)
	return "player_" .. player.UserId
end

-- Возвращает (данные, успех). При неудаче сохранять нельзя, чтобы не затереть прогресс.
local function fetch(player)
	if not store then
		return nil, false
	end
	local attempts = if RunService:IsStudio() then 1 else 3
	for attempt = 1, attempts do
		local ok, result = pcall(store.GetAsync, store, keyFor(player))
		if ok then
			return result, true
		end
		warn("[PlayerData] Не удалось загрузить данные", player.Name, result)
		if attempt < attempts then
			task.wait(attempt * 2)
		end
	end
	return nil, false
end

local function save(player, profile)
	if not (store and profile.canSave) then
		return
	end
	local data = {}
	for key, value in profile.values do
		data[key] = value.Value
	end
	activeSaves += 1
	local ok, err = pcall(store.SetAsync, store, keyFor(player), data, { player.UserId })
	activeSaves -= 1
	if not ok then
		warn("[PlayerData] Не удалось сохранить данные", player.Name, err)
	end
end

local function load(player)
	local saved, ok = fetch(player)
	if not player.Parent then
		return -- игрок вышел, пока грузились данные
	end
	local leaderstats = Instance.new("Folder")
	leaderstats.Name = "leaderstats"
	local values = {}
	for _, stat in Config.Stats do
		local value = Instance.new("IntValue")
		value.Name = stat.Name
		value.Value = type(saved) == "table" and tonumber(saved[stat.Key]) or 0
		value.Parent = leaderstats
		values[stat.Key] = value
	end
	leaderstats.Parent = player
	profiles[player] = { values = values, canSave = ok }
end

function PlayerData.increment(player, key, delta)
	local profile = profiles[player]
	if profile then
		profile.values[key].Value += delta
	end
end

function PlayerData.start()
	Players.PlayerAdded:Connect(load)
	for _, player in Players:GetPlayers() do
		task.spawn(load, player)
	end

	Players.PlayerRemoving:Connect(function(player)
		local profile = profiles[player]
		if profile then
			profiles[player] = nil
			save(player, profile)
		end
	end)

	game:BindToClose(function()
		for player, profile in profiles do
			profiles[player] = nil
			task.spawn(save, player, profile)
		end
		local deadline = os.clock() + 25
		while activeSaves > 0 and os.clock() < deadline do
			task.wait()
		end
	end)

	task.spawn(function()
		while true do
			task.wait(Config.AutosaveInterval)
			for player, profile in profiles do
				task.spawn(save, player, profile)
			end
		end
	end)
end

return PlayerData
