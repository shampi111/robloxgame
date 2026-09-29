-- Цикл раунда: лобби → подвал (ключи, монстр) → лес (генератор, Тень) → машина.
-- Состояние раунда хранится в атрибутах ReplicatedStorage.GameState, у игроков —
-- атрибуты InRound (участвует ли в раунде) и Zone ("Maze" или "Forest").
local Players = game:GetService("Players")
local ReplicatedStorage = game:GetService("ReplicatedStorage")
local TweenService = game:GetService("TweenService")

local Config = require(ReplicatedStorage.Shared.Config)
local ForestBuilder = require(script.Parent.ForestBuilder)
local MapBuilder = require(script.Parent.MapBuilder)
local Monster = require(script.Parent.Monster)
local PlayerData = require(script.Parent.PlayerData)
local Shadow = require(script.Parent.Shadow)
local scare = require(script.Parent.Scare)

local remotes = ReplicatedStorage.Remotes
local state = ReplicatedStorage.GameState

local ARRIVAL_FREEZE = 2 -- секунд заморозки после переноса, пока грузится пол
local FALL_LIMIT = -20 -- ниже этой высоты игрок считается провалившимся

local GameLoop = {}

local function notifyAll(text, kind)
	remotes.Notify:FireAllClients(text, kind)
end

local function setPhase(phase, timeLeft)
	state:SetAttribute("Phase", phase)
	state:SetAttribute("TimeLeft", timeLeft)
end

local function survivors()
	local result = {}
	for _, player in Players:GetPlayers() do
		if player:GetAttribute("InRound") then
			table.insert(result, player)
		end
	end
	return result
end

local function playerFromHit(hit)
	local character = hit:FindFirstAncestorOfClass("Model")
	return character and Players:GetPlayerFromCharacter(character)
end

-- Звук на детали (3D), если его id задан в Config.Sounds.
local function playSound(parent, name, looped)
	local id = Config.Sounds[name]
	if id == "" then
		return
	end
	local sound = Instance.new("Sound")
	sound.SoundId = id
	sound.Looped = looped
	sound.RollOffMaxDistance = 120
	sound.Parent = parent
	sound:Play()
end

local function prompt(parent, actionText, objectText, holdDuration)
	local proximityPrompt = Instance.new("ProximityPrompt")
	proximityPrompt.ActionText = actionText
	proximityPrompt.ObjectText = objectText
	proximityPrompt.HoldDuration = holdDuration
	proximityPrompt.MaxActivationDistance = 10
	proximityPrompt.RequiresLineOfSight = false
	proximityPrompt.Parent = parent
	return proximityPrompt
end

local function isInZone(player, zone)
	return player:GetAttribute("InRound") and player:GetAttribute("Zone") == zone
end

local function openExitDoor(layout)
	state:SetAttribute("ExitOpen", true)
	local door = layout.door
	door.Color = Config.Colors.DoorOpen
	playSound(door, "DoorOpen", false)
	-- Дверь уезжает в потолок.
	TweenService:Create(door, TweenInfo.new(2, Enum.EasingStyle.Quad), {
		CFrame = door.CFrame + Vector3.new(0, Config.Maze.WallHeight - 0.5, 0),
	}):Play()
	notifyAll("Все ключи найдены! Дверь ВЫХОД открыта!", "exit")
end

local function setupKeys(layout)
	local total = #layout.keys
	state:SetAttribute("KeysFound", 0)
	state:SetAttribute("KeysTotal", total)
	state:SetAttribute("ExitOpen", false)
	for _, key in layout.keys do
		prompt(key, "Подобрать", "Ключ", 0.4).Triggered:Connect(function(player)
			if not isInZone(player, "Maze") or not key.Parent then
				return
			end
			playSound(key.Parent, "KeyPickup", false)
			key:Destroy()
			local found = state:GetAttribute("KeysFound") + 1
			state:SetAttribute("KeysFound", found)
			PlayerData.increment(player, "Keys", 1)
			notifyAll(string.format("%s находит ключ (%d/%d)", player.DisplayName, found, total), "key")
			if found >= total then
				openExitDoor(layout)
			end
		end)
	end
	if total == 0 then
		openExitDoor(layout)
	end
end

local function setupForest(forest, round)
	state:SetAttribute("GeneratorOn", false)

	local generatorPrompt =
		prompt(forest.generator, "Запустить", "Генератор", Config.Forest.GeneratorHold)
	-- Генератор заводится с грохотом — Тень сразу слышит.
	generatorPrompt.PromptButtonHoldBegan:Connect(function(player)
		if isInZone(player, "Forest") and round.shadow then
			round.shadow:attract(player)
			remotes.Notify:FireClient(
				player,
				"Генератор грохочет... что-то приближается",
				"danger"
			)
		end
	end)

	local carPrompt = prompt(forest.car, "Уехать", "Машина", 1.5)
	carPrompt.Enabled = false

	generatorPrompt.Triggered:Connect(function(player)
		if not isInZone(player, "Forest") or state:GetAttribute("GeneratorOn") then
			return
		end
		state:SetAttribute("GeneratorOn", true)
		generatorPrompt.Enabled = false
		carPrompt.Enabled = true
		forest:powerOn()
		playSound(forest.generator, "Generator", true)
		notifyAll(
			player.DisplayName
				.. " запускает генератор! Ворота открыты — бегите к машине!",
			"exit"
		)
	end)

	carPrompt.Triggered:Connect(function(player)
		if not isInZone(player, "Forest") then
			return
		end
		player:SetAttribute("InRound", false)
		round.escaped += 1
		PlayerData.increment(player, "Escapes", 1)
		notifyAll(player.DisplayName .. " уезжает отсюда. Побег удался!", "escape")
		player:LoadCharacter()
	end)
end

-- Переносит персонажа и ненадолго замораживает его, чтобы он не провалился,
-- если пол на новом месте у игрока ещё не загрузился.
local function moveCharacter(player, position)
	local character = player.Character
	local root = character and character:FindFirstChild("HumanoidRootPart")
	if not root then
		return
	end
	pcall(player.RequestStreamAroundAsync, player, position)
	root.Anchored = true
	character:PivotTo(CFrame.new(position))
	task.delay(ARRIVAL_FREEZE, function()
		if root.Parent then
			root.Anchored = false
		end
	end)
end

local function teleportIntoMaze(layout)
	local participants = 0
	for _, player in Players:GetPlayers() do
		local character = player.Character
		local humanoid = character and character:FindFirstChildOfClass("Humanoid")
		if humanoid and humanoid.Health > 0 then
			participants += 1
			moveCharacter(player, layout:startPosition(participants))
			player:SetAttribute("Zone", "Maze")
			player:SetAttribute("InRound", true)
		end
	end
	return participants
end

-- Страховка: провалившегося сквозь пол игрока возвращаем на старт его локации.
local function rescueFallen(layout)
	for _, player in survivors() do
		local character = player.Character
		local root = character and character:FindFirstChild("HumanoidRootPart")
		if root and root.Position.Y < FALL_LIMIT then
			local position = if player:GetAttribute("Zone") == "Forest"
				then layout.forestEntry + Vector3.new(6, 3, 0)
				else layout:startPosition(math.random(1, 9))
			moveCharacter(player, position)
		end
	end
end

-- Карта строится заранее, пока игроки ждут в лобби: у всех клиентов
-- есть время её загрузить до переноса в подвал.
local function prepareRound()
	local rng = Random.new()
	local layout = MapBuilder.buildMaze(rng)
	local forest = ForestBuilder.build(rng, layout.forestEntry)
	local round = { layout = layout, forest = forest, escaped = 0, shadow = nil }
	setupKeys(layout)
	setupForest(forest, round)
	return round
end

local function playRound(round)
	local layout, forest = round.layout, round.forest

	-- Выход из подвала в лес.
	local exitConnection = layout.exitZone.Touched:Connect(function(hit)
		local player = playerFromHit(hit)
		if player and isInZone(player, "Maze") then
			player:SetAttribute("Zone", "Forest")
			remotes.Notify:FireClient(
				player,
				"Свежий воздух... но это ещё не конец. Найдите генератор.",
				"info"
			)
		end
	end)

	local participants = teleportIntoMaze(layout)
	local monster, shadow
	if participants > 0 then
		notifyAll(
			string.format("Найдите все ключи (%d) и откройте выход...", #layout.keys),
			"info"
		)
		shadow = Shadow.new(forest)
		shadow:start()
		round.shadow = shadow

		task.spawn(function()
			while layout.folder.Parent do
				rescueFallen(layout)
				task.wait(0.2)
			end
		end)

		for timeLeft = Config.RoundTime, 0, -1 do
			setPhase("Playing", timeLeft)
			if not monster and Config.RoundTime - timeLeft >= Config.MonsterDelay then
				monster = Monster.new(layout)
				monster:start()
				notifyAll("Оно проснулось...", "danger")
			end
			if #survivors() == 0 then
				break
			end
			task.wait(1)
		end
	end

	-- Кто не успел — достаётся тьме.
	local remaining = survivors()
	for _, player in remaining do
		scare(player, player:GetAttribute("Zone") == "Forest" and "Shadow" or "Monster")
	end

	local message
	if participants == 0 then
		message = "Раунд отменён: некому играть"
	elseif round.escaped == 0 then
		message = if #remaining > 0
			then "Время вышло. Никто не выбрался..."
			else "Никто не выбрался..."
	elseif round.escaped == participants then
		message = "Все сбежали! На этот раз..."
	else
		message = string.format("Сбежали: %d из %d", round.escaped, participants)
	end
	setPhase("Ending", Config.EndScreenTime)
	notifyAll(message, round.escaped > 0 and "escape" or "danger")
	task.wait(Config.EndScreenTime)

	exitConnection:Disconnect()
	if monster then
		monster:destroy()
	end
	if shadow then
		shadow:destroy()
	end
	layout.folder:Destroy()
	forest:destroy()
end

function GameLoop.start()
	local function onPlayerAdded(player)
		player.CharacterAdded:Connect(function(character)
			-- Новый персонаж всегда появляется в лобби.
			player:SetAttribute("InRound", false)
			player:SetAttribute("Zone", nil)
			local humanoid = character:WaitForChild("Humanoid")
			humanoid.Died:Connect(function()
				player:SetAttribute("InRound", false)
			end)
		end)
	end
	Players.PlayerAdded:Connect(onPlayerAdded)
	for _, player in Players:GetPlayers() do
		onPlayerAdded(player)
	end

	task.spawn(function()
		while true do
			while #Players:GetPlayers() < Config.MinPlayers do
				setPhase("Waiting", 0)
				task.wait(1)
			end
			local round = prepareRound()
			for timeLeft = Config.IntermissionTime, 1, -1 do
				setPhase("Intermission", timeLeft)
				task.wait(1)
			end
			playRound(round)
		end
	end)
end

return GameLoop
