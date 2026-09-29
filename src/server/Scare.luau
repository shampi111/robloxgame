-- Поимка игрока: скример на экране и смерть. kind — кто поймал ("Monster" или "Shadow").
local ReplicatedStorage = game:GetService("ReplicatedStorage")

local remotes = ReplicatedStorage.Remotes

local MESSAGES = {
	Monster = "Оно поймало тебя...",
	Shadow = "Не стоило отводить взгляд...",
}

return function(player, kind)
	player:SetAttribute("InRound", false)
	remotes.Jumpscare:FireClient(player, kind)
	remotes.Notify:FireClient(player, MESSAGES[kind] or MESSAGES.Monster, "danger")
	local character = player.Character
	local humanoid = character and character:FindFirstChildOfClass("Humanoid")
	if humanoid then
		humanoid.Health = 0
	end
end
