# 🤖 Mini-Projet ROS 2 : Le Roomba Virtuel (V2)

> **Pré-requis :** avoir terminé la [V1](sujet_roomba_v1.md). Cette V2 **reprend et étend** le projet existant (`custom_interfaces` + `virtual_roomba`) ; on ne repart pas de zéro.

La V1 étais destinée à la découverte des **paramètres**, des **topics** et des **services**. Cette V2 ajoute trois notions qui complètent le tableau de ROS 2 :

- les **Actions** pour les tâches **longues, avec retour de progression (feedback) et annulables** : une mission de nettoyage d'une surface donnée ;
- les **Fichiers de launch** (+ fichier de configuration YAML) pour démarrer tout le système en **une seule commande** ;
- le **monitoring du changement de paramètres** à chaud, pour qu'un `ros2 param set` soit pris en compte **en cours d'exécution** et validé.

Le projet reste **en Python (`rclpy`)**, **sans interface graphique ni simulateur**, cible **ROS 2 Jazzy**.

---

## 🧭 Pourquoi une action ici ?

En V1, `toggle_cleaning` (un **service**) démarre/arrête le nettoyage de façon **instantanée et indéfinie** : on dit « commence », ça répond « ok », et le robot nettoie jusqu'à ce qu'on dise « arrête » ou que la batterie soit vide.

Une **mission « nettoie 20 m² »** est différente : elle a une **durée**, on veut **suivre sa progression**, pouvoir **l'annuler en cours de route**, et obtenir un **résultat final**. C'est exactement le rôle d'une **action** (goal → feedback continu → result), là où un service ne sait que répondre une fois.

👉 On **garde** `toggle_cleaning` (nettoyage manuel libre) **et** on **ajoute** l'action `CleanArea` (mission bornée). Le but est de bien voir *quand* choisir l'un ou l'autre.

---

## 🏗️ Architecture attendue

On enrichit les **deux packages existants** (pas de nouveau package) :

```
src/
├── custom_interfaces/
│   ├── msg/RoombaState.msg          (V1, inchangé)
│   ├── srv/SetPowerMode.srv         (V1, inchangé)
│   ├── srv/ToggleCleaning.srv       (V1, inchangé)
│   └── action/CleanArea.action      ⟵ NOUVEAU
└── virtual_roomba/
    ├── virtual_roomba/
    │   ├── py_robot_core.py         ⟵ ÉTENDU (action server + param callback)
    │   └── py_dashboard_cli.py      ⟵ ÉTENDU (action client)
    ├── launch/
    │   └── roomba.launch.py         ⟵ NOUVEAU
    └── config/
        └── roomba_params.yaml       ⟵ NOUVEAU
```

---

## 🛠️ Étape 1 : L'interface d'action `action/CleanArea.action`

Une définition d'action a **trois parties** séparées par `---` : le **goal** (requête), le **result** (réponse finale), le **feedback** (mises à jour intermédiaires).

```
# Goal : ce que l'appelant demande
float32 target_area        # surface à nettoyer, en m²
---
# Result : renvoyé une seule fois, à la fin
bool success               # True si la surface a été entièrement nettoyée
float32 cleaned_area       # surface réellement nettoyée (m²)
string message             # détail lisible (terminé, annulé, batterie morte…)
---
# Feedback : publié périodiquement pendant la mission
float32 cleaned_area       # m² déjà nettoyés
float32 progress           # avancement en % (0 à 100)
float32 battery_level      # batterie courante, pour suivre la mission
```

**Configuration du build à compléter** dans `custom_interfaces` :

- `package.xml` : ajouter une dépendance `<depend>action_msgs</depend>` (les actions s'appuient dessus pour la gestion des goals).
- `CMakeLists.txt` : ajouter le fichier d'action à l'appel existant :
  ```cmake
  rosidl_generate_interfaces(${PROJECT_NAME}
    "msg/RoombaState.msg"
    "srv/SetPowerMode.srv"
    "srv/ToggleCleaning.srv"
    <rajouter_dépendance>              # ⟵ Nouvelle action à rajouter
    DEPENDENCIES action_msgs           # ⟵ NOUVEAU
  )
  ```

> Après `colcon build`, vérifie que l'action existe avec la bonne commande.

---

## 🧠 Étape 2 : Étendre le node `py_robot_core`

### 2.a — Nouveau paramètre : `cleaning_speed`

En plus de `drain_rate` (V1), le robot déclare un paramètre **`cleaning_speed`** (en **m²/s**) : la vitesse à laquelle il nettoie pendant une mission. Valeur de référence configurable au lancement.

### 2.b — Monitoring du changement de paramètres (à chaud)

En V1, `drain_rate` n'était lu **qu'au lancement**. On veut maintenant pouvoir le modifier **en cours d'exécution** via `ros2 param set` et que le robot **réagisse immédiatement**.

- Enregistre un **callback de validation** via le mécanisme de monitoring de changement de tous les paramètres (`event_callback`).
- Dans ce callback, pour chaque paramètre modifié :
  * `drain_rate` : **refuser** (`SetParametersResult(successful=False, ...)`) si la valeur est **négative** ; sinon mettre à jour le **taux de référence** `base_drain_rate`, puis faire en sorte que le nouveau `drain_rate` soit appliqué en fonction du mode actuel.
  * `cleaning_speed` : **refuser** si `<= 0`, sinon l'appliquer.
- Log chaque changement accepté/refusé pour qu'on le voie dans le terminal.

> ⚠️ Le callback doit **retourner** un `rcl_interfaces.msg.SetParametersResult`. S'il refuse, l'ancienne valeur est conservée.

### 2.c — Le serveur d'action `clean_area`

Crée un `ActionServer` (de `rclpy.action`) sur le nom **`clean_area`**, type `CleanArea`, hébergé dans `py_robot_core` (c'est le « cerveau » qui pilote le nettoyage). Comportement de l'exécution d'un goal :

1. **Refus en amont** (`goal_callback`) : refuser le goal (`GoalResponse.REJECT`) si le robot est `"DEAD"`, si `target_area <= 0`, ou si une mission/un nettoyage est déjà en cours (pas de double mission).
2. **Pendant l'exécution** (`execute_callback`), à **1 Hz** :
   * passe le statut à `"CLEANING"` ;
   * augmente la surface nettoyée de `cleaning_speed` (× 1 s) ;
   * décharge la batterie de `drain_rate` (cohérent avec la logique V1) ;
   * **publie un feedback** (`cleaned_area`, `progress`, `battery_level`) ;
   * **gère l'annulation** : si `goal_handle.is_cancel_requested`, appelle `goal_handle.canceled()` et renvoie un result `success=False` avec un message « annulé » ;
   * **gère la batterie morte** : si la batterie atteint 0, statut `"DEAD"`, `goal_handle.abort()`, result `success=False` « batterie épuisée ».
3. **Fin nominale** : quand `cleaned_area >= target_area`, repasse le statut à `"IDLE"`, appelle `goal_handle.succeed()` et renvoie `success=True`, `cleaned_area` final, message de réussite.

> 💡 Comme le timer de télémétrie (V1) et l'action tournent en parallèle, pense à **protéger l'état partagé** (statut, batterie) — au minimum, garde une logique cohérente entre le tick du timer et la boucle de l'action. Utiliser un `MultiThreadedExecutor` est un choix raisonnable à justifier.

L'état (`RoombaState`) continue d'être **publié à 1 Hz** sur `roomba_telemetry` comme en V1, pendant et hors mission.

---

## 💻 Étape 3 : Étendre le node `py_dashboard_cli`

Le dashboard devient aussi un **client d'action**.

- Instancie un `ActionClient(self, CleanArea, 'clean_area')` et attends le serveur (`wait_for_server`).
- Envoie un goal avec `send_goal_async(goal, feedback_callback=...)` :
  * le **feedback_callback** logue la progression, ex. :
    > *[Dashboard] Mission : 12.0 m² nettoyés (60.0 %) — Batterie 73.5 %*
  * récupère le **goal handle** (`add_done_callback`) et vérifie qu'il est **accepté** (`goal_handle.accepted`) ;
  * récupère le **result** via `get_result_async` et logue le bilan final (succès, surface, message).
- Montre **au moins une fois** comment **annuler** une mission en cours (`goal_handle.cancel_goal_async`), par ex. déclenché après quelques secondes.

> Pour cette V2, le déclenchement (mode, toggle, lancement de mission, annulation) peut rester piloté depuis le `main` / les arguments de ligne de commande, comme en V1. Garde les appels **non bloquants** pour ne pas figer le spin.

---

## 🚀 Étape 4 : Fichier de launch + configuration

**Objectif :** démarrer les deux nodes en **une seule commande**, avec le YAML comme **source de vérité des valeurs par défaut**, et la possibilité de **surcharger ponctuellement** un paramètre en ligne de commande.

> ⚠️ **Emplacement des fichiers.** `launch/` et `config/` doivent être **dans le package** (`src/virtual_roomba/launch/` et `src/virtual_roomba/config/`), **pas** à la racine de `src/`. Sinon `colcon` ne les installe pas.

### 4.a — Fichier de paramètres `config/roomba_params.yaml`

```yaml
py_robot_core:
  ros__parameters:
    drain_rate: 2.0
    cleaning_speed: 1.0
```

> 🔑 **Piège classique :** la clé de premier niveau du YAML doit être **le nom du node au runtime** (ici `py_robot_core`, celui passé à `super().__init__(...)` et au `name=` du launch), et **non** le nom de l'exécutable (`robot_core`). Si la clé ne correspond pas, ROS **ignore le fichier en silence** et le node retombe sur les valeurs par défaut codées en dur — sans aucune erreur. C'est très difficile à diagnostiquer, vérifie ce point en premier si tes paramètres YAML « ne s'appliquent pas ».

### 4.b — Launch file `launch/roomba.launch.py`

Le launch doit, dans l'ordre :

1. déclarer un **argument de launch** `drain_rate` (`DeclareLaunchArgument`) servant de **surcharge optionnelle** ;
2. lancer `robot_core` (exécutable `robot_core`, node nommé `py_robot_core`) en lui passant le **chemin du YAML installé**, obtenu avec `get_package_share_directory('virtual_roomba')` (jamais un chemin relatif `..`, qui casse après le build) ;
3. lancer `dashboard_cli` ;
4. *(optionnel)* `output='screen'` pour voir les logs des deux nodes dans le même terminal.

**🎯 Le comportement de priorité à obtenir :**

| Commande | `drain_rate` | `cleaning_speed` |
|---|---|---|
| `ros2 launch virtual_roomba roomba.launch.py` | YAML | YAML |
| `... roomba.launch.py drain_rate:=5.0` | **5.0** (CLI surcharge) | YAML |

**⚠️ Deux pièges à éviter** (et la raison du pattern recommandé ci-dessous) :

- Si tu passes **toujours** `parameters=[config, {'drain_rate': LaunchConfiguration('drain_rate')}]`, l'entrée du dictionnaire (appliquée **après** le YAML) **écrase systématiquement** la valeur du YAML → le YAML n'est plus la source de vérité.
- Un `LaunchConfiguration` est **toujours une chaîne**. Si son défaut est `''` (pour "non fourni"), tu transmets `drain_rate=''` au node, et `declare_parameter('drain_rate', 0.1)` (type `DOUBLE`) **plante** : *"Trying to set parameter 'drain_rate' to '' of type 'STRING'"*.

**Pattern recommandé — n'ajouter le paramètre que s'il est fourni**, grâce à une `OpaqueFunction` (seule capable de lire la **valeur réelle** d'un `LaunchConfiguration` au lancement, via `.perform(context)`).

### 4.c — Exposer launch et config au build

Dans `setup.py` de `virtual_roomba`, ajoute les dossiers aux `data_files` pour qu'ils soient installés.

Utilisation attendue :

```bash
ros2 launch virtual_roomba roomba.launch.py
ros2 launch virtual_roomba roomba.launch.py drain_rate:=5.0   # surcharge CLI
```

---

## 🔧 Étape 5 : Vérifier le monitoring des paramètres

Une fois le système lancé, sans rien redémarrer :

```bash
ros2 param get /py_robot_core drain_rate
ros2 param set /py_robot_core drain_rate 8.0     # accepté → décharge plus rapide en direct
ros2 param set /py_robot_core drain_rate -1.0    # refusé par le callback de validation
ros2 param set /py_robot_core cleaning_speed 0   # refusé (<= 0)
```

Tu dois voir dans les logs du robot la prise en compte (ou le refus) **immédiate**, et l'effet visible sur la télémétrie côté dashboard.

---

## 🚦 Critères de réussite

1. `custom_interfaces` compile avec l'action `CleanArea` (`ros2 interface show` la liste) et `action_msgs` est bien déclaré.
2. `ros2 launch virtual_roomba roomba.launch.py` démarre **les deux nodes** ; le dashboard affiche un robot **plein (100 %), IDLE, NORMAL**.
3. L'argument de launch fonctionne : `drain_rate:=5.0` change bien la valeur lue par le robot au démarrage.
4. Une mission `clean_area` (ex. 20 m²) **publie un feedback de progression** côté dashboard, fait **décroître la batterie**, puis renvoie un **result de succès**.
5. **Annuler** une mission en cours est pris en compte : le robot s'arrête et le result indique l'annulation.
6. Une mission lancée avec une **batterie insuffisante** se termine en **abort** (batterie morte), sans erreur.
7. `ros2 param set /py_robot_core drain_rate <valeur>` est pris en compte **à chaud** ; une valeur **négative est refusée** par le callback.
8. Le robot **refuse** un second goal pendant qu'une mission est déjà en cours, et refuse toute mission s'il est `"DEAD"`.

---

## 🧪 Pour aller plus loin (bonus, facultatif)

- Déplacer le serveur d'action dans un **3ᵉ node dédié** et discuter du partage d'état avec le robot_core.
- Ajouter une **politique de qualité de service (QoS)** explicite sur la télémétrie et la justifier.
- Permettre au launch de **choisir le mode de puissance initial** via un second argument de launch.
