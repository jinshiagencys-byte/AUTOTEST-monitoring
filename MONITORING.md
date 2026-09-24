# Monitoring : génération séparée du rejeu

## Architecture

Le nouveau parcours se trouve dans
`/home/bill/AUTOTEST/autotest_package/autotest/monitoring/`.
Le CLI AUTOTEST historique reste disponible ; **il ne faut pas utiliser son
`run_workflow` pour un cycle de monitoring**, car il mélange analyse et exécution.

### Phase A — génération explicite uniquement

- Réutilise `URLExtractor.extract_urls` pour le crawl BFS et
  `WebTestGenerator` pour le DOM, les métadonnées, les cas et le script par page.
- Ajoute un mode non interactif à la génération de cas et un contrat de script
  spécifique au monitoring. Aucun test généré n'est exécuté pendant cette phase.
- Conserve chaque version dans un dossier horodaté avec URL du site, URL de page,
  date UTC, fournisseur, cas de test, métadonnées et SHA-256 du script.
- Remplace le pointeur du manifeste uniquement après validation. Une erreur de
  génération conserve l'ancienne version et la demande de régénération.
- Stockage choisi : **fichiers versionnables dans Git**, pas Supabase. Les commits
  ne sont pas automatiques : inspecter les scripts et métadonnées avant de les
  versionner. Ne jamais y stocker de secrets ou données personnelles.

### Phase B — sans LLM

- Charge le manifeste, vérifie le SHA-256 et le contrat Python avant chaque rejeu.
- Lance un processus et un navigateur isolés par page ; délai maximal configurable
  (120 secondes par défaut), nettoyage du groupe de processus sous Linux.
- Injecte le runtime Selenium : options Chrome de `browser.py`, distribution de
  délais de `mimic_typing.py`, Bézier et constantes de Fitts de `mouse_trajectory.py`.
  Attribution et licence dans
  `/home/bill/AUTOTEST/autotest_package/autotest/monitoring/NOTICE`.
- Résolution sémantique : texte, aria-label, placeholder, rôle, nom, identifiant
  stable ; doublons masqués ignorés, correspondances ambiguës refusées.
- Ni import de fournisseur LLM, ni génération, ni décision LLM dans le rejeu.
  Les variations aléatoires concernent uniquement le mouvement et la frappe.

| Situation | Statut | Motif | Régénération automatique |
|---|---|---|---|
| Toutes les assertions passent | OK | completed | Non |
| Cible absente après attente | SKIP | dom_changed | Oui, via file persistante |
| Cible présente mais masquée, désactivée ou ambiguë | SKIP | element_not_ready | Non |
| Cible trouvée, résultat incorrect | FAIL | assertion_failed | Non |
| Challenge antibot reconnu | SKIP | bot_blocked | Non |
| Navigateur, script invalide ou délai dépassé | SKIP | browser_error / execution_error / execution_timeout | Non |

Une page s'arrête à la première erreur, sans interrompre les autres pages.
Un `SKIP` n'est **jamais une preuve de bon fonctionnement**. Les demandes de
régénération sont dédupliquées et ne sont consommées que par une Phase A séparée.

### Phase C — frontière JSON, jugement non modifié

Ce dépôt ne contient pas SentinelSite, son `resolve_target`, ni le jugement
Cloudflare GLM / Needle3 décrit dans le besoin. Aucun fournisseur ou modèle de
jugement n'a donc été ajouté ou modifié. Le fichier produit par `run --output`
est à transmettre à cette intégration externe : `pages` contient les résultats
bruts OK/SKIP/FAIL, leur motif, la version du script et le flag `regenerate`.
Le verdict global ne revient jamais dans le navigateur.

## Installation

Linux, Python compatible avec les dépendances AUTOTEST existantes, Chrome et
ChromeDriver compatible (ou Selenium Manager avec accès réseau au premier lancement).

```sh
python3 -m venv /home/bill/AUTOTEST/.venv
/home/bill/AUTOTEST/.venv/bin/pip install -r /home/bill/AUTOTEST/autotest_package/requirements.txt
export PYTHONPATH=/home/bill/AUTOTEST/autotest_package
```

La Phase A utilise les fournisseurs AUTOTEST existants (`--provider` :
1 OpenAI, 2 Groq, 3 Gemini, 4 Anthropic, 5 Ollama) et leur configuration existante.
Charger les clés par variables d'environnement ou via le fichier `.env` ignoré
par Git. Le choix de ces fournisseurs concerne la génération, pas la Phase C.
SQLAlchemy, déjà utilisé par AUTOTEST mais absent de ses dépendances déclarées,
est désormais déclaré.

Une machine dédiée au seul rejeu peut installer **seulement Selenium 4.15.2**,
avec le code du dépôt accessible par `PYTHONPATH` ; aucune clé LLM n'y est requise.
Les variables `MONITOR_CHROME_BINARY` et `MONITOR_CHROMEDRIVER` permettent de fixer
les chemins des exécutables. Chrome s'exécute avec son sandbox, sans privilège root.

## Commandes

Remplacer `https://example.com/` par un site dont vous autorisez le monitoring.
Employer toujours la même URL de site, barre finale comprise : elle identifie le
stockage et la file. Les chemins ci-dessous correspondent à ce dépôt.

```sh
export PYTHONPATH=/home/bill/AUTOTEST/autotest_package

# Génération initiale ou mensuelle ; pas de rejeu dans cette commande.
/home/bill/AUTOTEST/.venv/bin/python -m autotest.monitoring generate \
  --site https://example.com/ --max-depth 2 \
  --store /home/bill/AUTOTEST/monitoring_artifacts

# Cycle de monitoring : aucun appel LLM.
/home/bill/AUTOTEST/.venv/bin/python -m autotest.monitoring run \
  --site https://example.com/ --page-timeout 120 \
  --store /home/bill/AUTOTEST/monitoring_artifacts \
  --output /home/bill/AUTOTEST/monitoring_reports/latest.json

# Action manuelle « régénérer », par exemple après un FAIL jugé suspect.
/home/bill/AUTOTEST/.venv/bin/python -m autotest.monitoring regenerate \
  --site https://example.com/ --page https://example.com/contact \
  --store /home/bill/AUTOTEST/monitoring_artifacts

# Worker séparé traitant les éléments absents signalés par la Phase B.
/home/bill/AUTOTEST/.venv/bin/python -m autotest.monitoring regenerate \
  --site https://example.com/ --pending \
  --store /home/bill/AUTOTEST/monitoring_artifacts
```

`--headed` affiche le navigateur si un serveur graphique est disponible.
Codes de retour du rejeu : 0 = tout OK, 1 = au moins un FAIL, 2 = SKIP ou erreur
de configuration. La génération retourne 2 si une page n'a pas pu être générée.

L'exemple de planification se trouve dans
`/home/bill/AUTOTEST/deploy/monitoring.crontab.example` : génération mensuelle,
worker de régénération toutes les dix minutes, rejeu toutes les cinq minutes.
Adapter domaine, fréquence et environnement puis ajouter ces lignes au crontab
de l'utilisateur. **Aucun cron n'a été installé automatiquement.** `flock` empêche
les chevauchements ; le stockage protège aussi ses mises à jour avec un verrou.

## Contrat des scripts

Chaque fichier `.py` définit `run(ctx)` et est exécutable **par le runner**, pas
comme un programme autonome. Il contient uniquement des appels littéraux :

```python
def run(ctx):
    ctx.open("https://example.com/contact")
    ctx.type_text({"aria_label": "Email"}, "monitor@example.test")
    ctx.assert_value({"placeholder": "Email"}, "monitor@example.test")
    ctx.assert_title("Contact")
```

Le runtime interprète les appels validés au lieu d'exécuter du Python arbitraire.
Cela impose réellement la saisie temporisée et les clics courbes, sans dépendre
de l'obéissance du LLM au prompt. Imports, `send_keys` brut, accès au driver,
XPath, gestion d'exceptions et appels réseau Python ne sont pas acceptés.
Les scripts Selenium historiques doivent être régénérés, pas copiés directement.
Assertions disponibles : visibilité, texte inclus, valeur exacte, titre exact,
URL exacte. Les vérifications attendent jusqu'à dix secondes.

## Limites opérationnelles

- Les options Chrome et gestes naturels **ne garantissent aucun passage de WAF**.
  Les heuristiques de challenge sont limitées. Il n'y a ni résolution de CAPTCHA,
  ni proxy rotatif, ni contournement d'un contrôle d'accès. Pour votre propre site,
  privilégier une règle WAF dédiée à une IP de monitoring autorisée, sans désactiver
  globalement la protection.
- Le crawl BFS hérité suit les liens HTML internes jusqu'à la profondeur fixée et
  normalise les URL en retirant requêtes/fragments. Il ne garantit pas une visite
  exhaustive des états SPA, pages authentifiées ou parcours sans liens HTML.
- Le contrat actuel ne prend pas en charge iframe, shadow DOM, téléversement,
  menus `select` ni parcours d'authentification multi-domaines. Une redirection
  hors origine interrompt le test. Ce contrôle applicatif n'est pas un pare-feu
  réseau : un navigateur charge normalement les ressources tierces d'une page.
- Une modification des libellés peut provoquer un SKIP ; celui-ci reste visible
  dans le rapport historique. Ne pas utiliser la régénération pour masquer une
  régression ; conserver les rapports importants et revoir les différences Git.
- Les scripts générés doivent être revus sur un environnement de test avant
  production. Le prompt exclut les opérations destructrices, mais ne remplace
  pas une validation métier ni des comptes et données de test dédiés.
- Les anciennes pages du manifeste ne sont pas supprimées implicitement lorsqu'un
  nouveau crawl ne les découvre plus. Leur retrait doit être une décision explicite.

## Validation

```sh
/home/bill/AUTOTEST/.venv/bin/pip install pytest
PYTHONPATH=/home/bill/AUTOTEST/autotest_package \
  /home/bill/AUTOTEST/.venv/bin/python -m pytest \
  /home/bill/AUTOTEST/autotest_package/tests/monitoring -q

MONITOR_LIVE_TEST=1 PYTHONPATH=/home/bill/AUTOTEST/autotest_package \
  /home/bill/AUTOTEST/.venv/bin/python -m pytest \
  /home/bill/AUTOTEST/autotest_package/tests/monitoring/test_browser_live.py -q
```

Le test réel démarre un serveur HTTP local et Chrome, vérifie la frappe, le clic,
les trois statuts et la file de régénération sans site tiers ni appel LLM.