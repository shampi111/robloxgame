-- Общие настройки игры. Модуль доступен и серверу, и клиенту:
-- меняйте числа здесь, чтобы настроить сложность и атмосферу.
local Config = {}

-- Раунд
Config.MinPlayers = 1
Config.IntermissionTime = 15 -- секунд в лобби перед раундом
Config.RoundTime = 300 -- секунд на побег
Config.MonsterDelay = 12 -- через сколько секунд после старта монстр просыпается
Config.EndScreenTime = 6
Config.KeysToEscape = 4

-- Лабиринт (генерируется заново каждый раунд)
Config.Maze = {
	Width = 10, -- клеток по X
	Height = 10, -- клеток по Z
	CellSize = 16, -- размер клетки в стадах
	WallHeight = 12,
	ExtraOpenings = 0.12, -- доля лишних проходов: петли, чтобы было куда убегать
	LampChance = 0.3, -- доля клеток с лампой на потолке
	FlickerChance = 0.5, -- доля ламп, которые мигают
	WallWritings = 8, -- сколько надписей на стенах (видны только при свете)
}

-- Лес за выходом из лабиринта (тоже генерируется заново каждый раунд)
Config.Forest = {
	Length = 360, -- от выхода из здания до забора с воротами
	Width = 300,
	TreeCount = 220,
	PathWidth = 8,
	PathSegments = 8, -- изгибы тропы
	LampSpacing = 45, -- фонари вдоль тропы (загораются от генератора)
	Logs = 14, -- поваленные брёвна
	Posters = 10, -- объявления «ПРОПАЛ» на деревьях
	GeneratorHold = 6, -- сколько секунд держать E, чтобы запустить генератор
}

-- Игрок
Config.WalkSpeed = 12
Config.SprintSpeed = 22
Config.StaminaMax = 100
Config.StaminaDrain = 22 -- в секунду во время бега
Config.StaminaRegen = 14 -- в секунду в покое
Config.StaminaRegenDelay = 1.2 -- пауза после бега перед восстановлением
Config.StaminaRecover = 0.3 -- после полного истощения бег снова доступен с этой доли

-- Монстр
Config.Monster = {
	WanderSpeed = 9,
	ChaseSpeed = 16, -- быстрее шага игрока, но медленнее бега
	SightRange = 90, -- видит игроков в прямой видимости на этом расстоянии
	HearRange = 14, -- слышит любого игрока в этом радиусе (даже за стеной)
	RunHearRange = 40, -- слышит бегущих игроков
	CatchRange = 4.5,
	SearchTime = 6, -- сколько секунд ищет там, где потерял игрока из виду
	HuntChance = 0.35, -- шанс, что при блуждании пойдёт туда, где сейчас игрок
	PauseAfterKill = 3,
}

-- Тень — существо из леса. Подкрадывается, пока на неё не смотрят,
-- замирает под взглядом и исчезает, если смотреть на неё достаточно долго.
Config.Shadow = {
	Speed = 11, -- чуть медленнее шага игрока
	AppearDistance = 45, -- на каком расстоянии появляется (за спиной у жертвы)
	ReappearDelay = 8, -- через сколько секунд после исчезновения возвращается
	StareTime = 2.5, -- сколько секунд смотреть, чтобы она исчезла
	ViewAngle = 35, -- угол взгляда, в градусах
	ViewDistance = 75,
	CatchRange = 4,
}

-- Текстуры из Creator Store: вставьте число из ссылки на ассет
-- (create.roblox.com/store/asset/<ЧИСЛО>/...). Подходят и декали, и картинки —
-- сервер сам достанет изображение из декали. 0 — встроенный материал Roblox.
Config.Textures = {
	Bark = 0, -- кора деревьев
	MazeWall = 0, -- стены лабиринта (грязный бетон, плитка)
	MazeFloor = 0, -- пол лабиринта
	Fence = 0, -- сетка-рабица на заборе (лучше с прозрачностью)
	Poster = 0, -- объявление «пропал без вести» на деревьях
	Scratches = 0, -- следы когтей на стенах лабиринта
	Blood = 0, -- пятна на полу лабиринта
}
Config.TextureTiles = { -- размер плитки текстуры в стадах
	Bark = 6,
	MazeWall = 8,
	MazeFloor = 8,
	Fence = 6,
}

-- Звуки: вставьте id из Creator Store в формате "rbxassetid://123456".
-- Пустая строка — звук отключён.
Config.Sounds = {
	Ambience = "", -- фоновый гул в лабиринте
	ForestAmbience = "", -- ветер/лес ночью
	Generator = "", -- работающий генератор (3D-звук)
	Chase = "", -- музыка погони
	Heartbeat = "", -- сердцебиение, когда монстр близко
	Monster = "", -- дыхание/рычание монстра (3D-звук)
	Jumpscare = "",
	KeyPickup = "",
	DoorOpen = "",
	Flashlight = "", -- щелчок фонаря
}

Config.WallWritings = {
	"ОНО РЯДОМ",
	"НЕ ОГЛЯДЫВАЙСЯ",
	"БЕГИ",
	"ТЫ НЕ ОДИН",
	"ВЫХОДА НЕТ",
	"ОНО СЛЫШИТ ШАГИ",
	"ТИШЕ...",
	"НЕ ВЫКЛЮЧАЙ СВЕТ",
	"ОНО ВИДИТ ТЕБЯ",
}

Config.Colors = {
	Wall = Color3.fromRGB(58, 54, 50),
	Pillar = Color3.fromRGB(40, 37, 35),
	Floor = Color3.fromRGB(34, 31, 29),
	Ceiling = Color3.fromRGB(24, 23, 23),
	Lamp = Color3.fromRGB(255, 212, 160),
	LampOff = Color3.fromRGB(60, 55, 50),
	Key = Color3.fromRGB(255, 200, 60),
	DoorLocked = Color3.fromRGB(110, 20, 20),
	DoorOpen = Color3.fromRGB(60, 200, 90),
	Writing = Color3.fromRGB(130, 0, 0),
	MonsterBody = Color3.fromRGB(12, 12, 14),
	MonsterEyes = Color3.fromRGB(255, 30, 30),
	ShadowBody = Color3.fromRGB(4, 4, 5),
	ShadowEyes = Color3.fromRGB(235, 240, 255),
	Grass = Color3.fromRGB(36, 44, 29),
	LeafyGrass = Color3.fromRGB(28, 38, 25),
	Mud = Color3.fromRGB(46, 37, 29),
	Bark = Color3.fromRGB(46, 38, 32),
	Pine = Color3.fromRGB(20, 34, 24),
	Metal = Color3.fromRGB(55, 58, 62),
	Generator = Color3.fromRGB(125, 95, 30),
	Car = Color3.fromRGB(60, 66, 74),
	LobbyWall = Color3.fromRGB(70, 58, 48),
	LobbyFloor = Color3.fromRGB(90, 70, 52),
}

Config.Stats = {
	{ Key = "Escapes", Name = "Побеги" },
	{ Key = "Keys", Name = "Ключи" },
}

Config.DataStoreName = "HorrorProgress_v1"
Config.AutosaveInterval = 120

return Config
