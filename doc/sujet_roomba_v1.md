# 🤖 Mini-Projet ROS 2 : Le Roomba Virtuel (V1)

L'objectif est de concevoir l'architecture logicielle simplifiée d'un robot aspirateur (type Roomba) **sans interface graphique ni simulateur**. Tout se passe dans le terminal. Voici les notions de qui seront utilisées dans ce mini projet :

- les **Paramètres** pour la configuration au lancement (`drain_rate`),
- les **Topics** pour la télémétrie continue (l'état publié à 1 Hz),
- les **Services** pour les actions instantanées (changer de mode, démarrer/arrêter le nettoyage).

Le projet se fait **en Python (`rclpy`)**.

---

## 🏗️ Architecture attendue

Créer **deux packages** distincts dans `src/` :

1. **`custom_interfaces`** (type `ament_cmake`) : il ne contient **que** les définitions d'interfaces (messages et services). En ROS 2, on isole toujours les interfaces dans leur propre package pour qu'elles puissent être réutilisées par d'autres nœuds (ici, par exemple, en C++ comme en Python).
2. **`virtual_roomba`** (type `ament_python`) : il contient les deux nœuds applicatifs et dépend de `custom_interfaces`.

```
src/
├── custom_interfaces/
│   ├── msg/RoombaState.msg
│   ├── srv/SetPowerMode.srv
│   └── srv/ToggleCleaning.srv
└── virtual_roomba/
    └── virtual_roomba/
        ├── py_robot_core.py
        └── py_dashboard_cli.py
```


---

## 🛠️ Étape 1 : Le package d'interfaces `custom_interfaces`

Crée le package puis ajoute les fichiers d'interfaces suivants.

### Topic (télémétrie) — `msg/RoombaState.msg`

```
float32 battery_level    # Niveau de batterie (0 à 100)
string current_status    # État du robot : "IDLE", "CLEANING" ou "DEAD"
string power_mode        # Mode de puissance courant : "NORMAL", "ECO" ou "TURBO"
```

### Service 1 (configuration) — `srv/SetPowerMode.srv`

```
string power_mode        # Mode demandé : "NORMAL", "ECO" ou "TURBO"
---
bool success             # True si le mode a été accepté
string message           # Détail lisible (mode appliqué, erreur, etc.)
```

### Service 2 (déclencheur) — `srv/ToggleCleaning.srv`

```
bool start_cleaning      # True = démarrer, False = arrêter
---
bool success
string message
```

**Configuration du build à vérifier :**

- Dans `CMakeLists.txt` : `find_package(rosidl_default_generators REQUIRED)` puis `rosidl_generate_interfaces(${PROJECT_NAME} ...)` listant les 3 fichiers.
- Dans `package.xml` : `buildtool_depend` sur `rosidl_default_generators`, `exec_depend` sur `rosidl_default_runtime`, et `<member_of_group>rosidl_interface_packages</member_of_group>`.

---

## 🧠 Étape 2 : Le nœud `py_robot_core`

C'est le "cerveau" du robot. Il vit dans le package `virtual_roomba` et dépend de `custom_interfaces`. Ses responsabilités :

* **Paramètre :** au lancement, le nœud déclare et lit un paramètre `drain_rate` (pourcentage de batterie perdu par seconde quand le robot nettoie). Cette valeur lue est mémorisée comme **taux de référence** (`base_drain_rate`), car les modes de puissance la modulent.

* **État interne initial :** batterie à `100.0`, statut `"IDLE"`, mode `"NORMAL"`.

* **Publisher (topic) :** publie un `RoombaState` sur le topic `roomba_telemetry` à **1 Hz** via un `Timer`.

* **Logique du Timer (à chaque tick d'1 s) :**
  * Si le statut est `"CLEANING"`, la batterie diminue de `drain_rate`.
  * Si la batterie atteint 0, elle est bornée à 0, le statut passe à `"DEAD"` et le nettoyage s'arrête.
  * Le message est ensuite publié quel que soit l'état.

* **Service `set_power_mode` (`SetPowerMode`) :** modifie le taux de décharge à partir du **taux de référence** :
  * `"NORMAL"` → `drain_rate = base_drain_rate` (taux de référence, mode par défaut)
  * `"ECO"`    → `drain_rate = base_drain_rate × 0.5`
  * `"TURBO"`  → `drain_rate = base_drain_rate × 2`
  * Un mode inconnu est refusé (`success = False`) avec un `message` explicite.
  * Si mode demandé = le mode courant, renvoie `success = True` sans rien changer.

* **Service `toggle_cleaning` (`ToggleCleaning`) :**
  * `start_cleaning = True` depuis `"IDLE"` → passe en `"CLEANING"`.
  * `start_cleaning = False` depuis `"CLEANING"` → revient en `"IDLE"`.
  * Si le robot est `"DEAD"`, toute demande est refusée (`success = False`).
  * Chaque réponse renvoie un `message` décrivant ce qui s'est passé.

---

## 💻 Étape 3 : Le nœud `py_dashboard_cli`

Interface utilisateur basique en ligne de commande, dans le package `virtual_roomba`.

* **Subscriber (topic) :** s'abonne à `roomba_telemetry` et logue chaque message reçu, par exemple :
  > *[Dashboard] Status: CLEANING | Battery: 85.5% | Mode: NORMAL*

* **Clients de services :** instancie un client pour `set_power_mode` et un pour `toggle_cleaning`, et attend leur disponibilité avec `wait_for_service`. Les appels sont **asynchrones** (`call_async` + `add_done_callback`) pour ne pas bloquer le spin du nœud.

* **Déclenchement :** pour cette V1, les appels peuvent être pilotés en dur depuis le `main` (par ex. via les arguments de ligne de commande) afin de tester le mode de puissance puis le démarrage du nettoyage.

---

## 📦 Configuration du package `virtual_roomba`

* `setup.py` : déclare les deux `console_scripts` (points d'entrée vers les `main` des deux nœuds).
* `package.xml` : `<build_type>ament_python</build_type>` et une dépendance d'exécution sur `custom_interfaces`.

---

## 🚦 Critères de réussite

1. Les deux packages compilent sans erreur avec `colcon build`.
2. `custom_interfaces` est bien configuré (`rosidl_default_generators`) et `virtual_roomba` déclare sa dépendance vers lui.
3. Au lancement des deux nœuds (deux terminaux), le dashboard affiche batterie à 100 %, statut `"IDLE"`, mode `"NORMAL"`.
4. En appelant `toggle_cleaning` (via `ros2 service call ...` ou via le dashboard), la batterie commence à descendre dans les logs du dashboard.
5. En appelant `set_power_mode "TURBO"`, la vitesse de décharge double par rapport au mode `"NORMAL"` ; en `"ECO"`, elle est divisée par deux.

