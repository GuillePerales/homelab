// Plantilla de /config/config.js (el real lleva las claves y no está en el repo)
module.exports = {
	// Prowlarr: URL Torznab de cada tracker privado (id del indexer en Prowlarr)
	torznab: [
		"http://PROWLARR:9696/<id-torrenteros>/api?apikey=<clave-prowlarr>",
		"http://PROWLARR:9696/<id-milnueve>/api?apikey=<clave-prowlarr>",
	],
	// Búsqueda por id (IMDb/TVDB) en vez de por nombre
	sonarr: ["http://SONARR:8989/?apikey=<clave-sonarr>"],
	radarr: ["http://RADARR:7878/?apikey=<clave-radarr>"],
	torrentClients: ["qbittorrent:http://<usuario>:<contraseña>@QBITTORRENT:8080"],
	useClientTorrents: true,

	// Biblioteca: también busca lo que ya está en media/
	dataDirs: ["/data/media/movies", "/data/media/tv"],
	linkDirs: ["/data/torrents/cross-seed"],
	linkType: "hardlink",
	linkCategory: "cross-seed-link",
	duplicateCategories: false,
	matchMode: "flexible",
	skipRecheck: true,
	action: "inject",

	// Ritmo prudente con los trackers privados
	delay: 60,
	searchCadence: "1 day",
	rssCadence: "30 minutes",
	excludeOlder: undefined,
	excludeRecentSearch: "2 weeks",
	searchLimit: 50,
};
