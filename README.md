# Небосвіт для Home Assistant

Інтеграція Home Assistant від застосунку **Небосвіт**: повітряні тривоги,
графіки відключень світла (ГПВ) і планові та аварійні відключення за вашою
адресою. Дані йдуть із сервера Небосвіт (`alarm-api.symonov.com`), ключі
до джерел зберігаються лише на сервері, у Home Assistant вводити нічого не треба.

Небосвіт — незалежний проєкт приватного розробника. Він не пов'язаний з
органами державної влади й не є застосунком «Повітряна тривога» чи продуктом
його розробників. Це не офіційний канал оповіщення: орієнтуйтеся на сирени та
офіційні державні застосунки. Джерела даних вказано в застосунку й на
<https://alarm-api.symonov.com/privacy>.

## Можливості

**Тривоги** (для області, району чи громади на вибір):
- зміни приходять одразу через WebSocket сервера; опитування раз на 30 с
  лишається запасним каналом;
- рівень (жовтий / червоний), тип загрози, з якого часу, деталі загроз від
  джерела;
- діагностичний сенсор «Дані про тривоги оновлено» показує, наскільки свіжі дані.

**Світло за графіком** (необов'язково; зона й черга):
- чи є світло зараз за графіком і коли наступна зміна;
- коли наступне відключення та ввімкнення, скільки хвилин без світла сьогодні;
- чи опубліковано графік на сьогодні й завтра, із джерелом і часом оновлення.

**Відключення за адресою** (необов'язково; населений пункт, вулиця, будинок):
- планові ремонти й аварійні відключення, які стосуються вашого будинку;
- адреса лишається в Home Assistant: сервер бачить лише, який населений пункт
  запитано, а вулицю й будинок інтеграція звіряє сама.

Графік — це лише графік, а не вимір напруги в мережі. «Світло є» показується
тільки тоді, коли графік на цей день опубліковано.

## Встановлення

### HACS
1. **HACS** → меню (⋮) → **Custom repositories**.
2. Додайте `https://github.com/symonovserhii/nebosvit-homeassistant`, категорія **Integration**.
3. Знайдіть **Nebosvit** і натисніть **Download**.
4. Перезапустіть Home Assistant.

### Вручну
Скопіюйте `custom_components/nebosvit` до `config/custom_components/` і
перезапустіть Home Assistant.

## Налаштування

**Налаштування → Пристрої та служби → Додати інтеграцію → Nebosvit**:
1. Адреса сервера (за замовчуванням `https://alarm-api.symonov.com`); ключ
   застосунку лишіть порожнім, якщо сервер його не вимагає.
2. Область, потім вся область, район або громада.
3. Графік відключень: зона й черга, або «—», щоб пропустити.
4. Відключення за адресою: зона оператора, назва населеного пункту, вибір зі
   списку, потім вулиця й будинок (можна залишити порожніми, тоді враховуються
   всі відключення населеного пункту). «—» пропускає цей крок.

Змінити місце, графік чи адресу можна пізніше без видалення інтеграції:
**Nebosvit → Налаштувати**.

## Сутності

Імена залежать від мови Home Assistant і назви місця; нижче — сутності та їхній
зміст (`<місце>` — назва пристрою, наприклад `kyiv`).

| Сутність | Зміст |
|---|---|
| `binary_sensor.<місце>_alert_active` | Тривога зараз (`on`/`off`); атрибути: рівень, усі тривоги з деталями |
| `sensor.<місце>_alert_level` | `clear` / `yellow` / `red` |
| `sensor.<місце>_threat_type` | Найважливіший тип загрози; усі типи й деталі — в атрибутах |
| `sensor.<місце>_alert_since` | Початок тривоги |
| `sensor.<місце>_alert_data_updated` | Коли сервер востаннє підтвердив дані (діагностика) |
| `sensor.<місце>_power_schedule` | Світло за графіком: `on` / `off` / `maybe_off` / `unknown`; інтервали сьогодні й завтра |
| `binary_sensor.<місце>_power_off_schedule` | `on`, коли за графіком світла немає (можливе відключення — в атрибуті `maybe_off`) |
| `sensor.<місце>_next_power_change` | Наступна зміна стану світла |
| `sensor.<місце>_next_power_cut` | Наступне відключення за графіком |
| `sensor.<місце>_power_back` | Коли світло з'явиться за графіком |
| `sensor.<місце>_off_today_by_schedule` | Хвилин без світла сьогодні |
| `sensor.<місце>_schedule_today` / `_schedule_tomorrow` | Стан графіка: `applies` / `waiting` / `not_applied` / `no_data` / `source_error` |
| `binary_sensor.<місце>_outage_at_address_now` | Відключення за вашою адресою зараз; атрибути: вид, причина, до коли |
| `sensor.<місце>_next_outage_at_address` | Початок наступного відключення за адресою; список найближчих — в атрибуті `upcoming` |

Точні `entity_id` видно в **Налаштування → Пристрої та служби → Nebosvit**.

## Приклади автоматизацій

### Тривога: червоне світло й голосове попередження
```yaml
alias: "Тривога: світло й голос"
triggers:
  - trigger: state
    entity_id: binary_sensor.kyiv_alert_active
    to: "on"
actions:
  - action: light.turn_on
    target:
      entity_id: light.living_room
    data:
      color_name: red
      brightness_pct: 100
  - action: tts.speak
    target:
      entity_id: tts.google_translate_uk
    data:
      media_player_entity_id: media_player.kitchen_speaker
      message: "Увага! Повітряна тривога. Пройдіть в укриття."
```

### Відбій
```yaml
alias: "Тривога: відбій"
triggers:
  - trigger: state
    entity_id: binary_sensor.kyiv_alert_active
    from: "on"
    to: "off"
actions:
  - action: light.turn_on
    target:
      entity_id: light.living_room
    data:
      color_name: white
  - action: notify.mobile_app_phone
    data:
      message: "Відбій повітряної тривоги."
```

### Світло вимкнуть за 15 хвилин
```yaml
alias: "Світло: попередження за 15 хв"
triggers:
  - trigger: template
    value_template: >
      {% set t = states('sensor.kyiv_next_power_cut') %}
      {{ t not in ['unknown', 'unavailable'] and
         0 < (as_timestamp(t) - as_timestamp(now())) <= 15 * 60 }}
actions:
  - action: notify.mobile_app_phone
    data:
      message: >
        За графіком світло вимкнуть о
        {{ as_timestamp(states('sensor.kyiv_next_power_cut')) | timestamp_custom('%H:%M') }}.
        Заряджайте пристрої.
```

### Аварійне відключення за адресою
```yaml
alias: "Аварійне відключення за адресою"
triggers:
  - trigger: state
    entity_id: binary_sensor.kyiv_outage_at_address_now
    to: "on"
conditions:
  - condition: template
    value_template: "{{ state_attr('binary_sensor.kyiv_outage_at_address_now', 'kind') == 'EMERGENCY' }}"
actions:
  - action: notify.mobile_app_phone
    data:
      message: >
        Аварійне відключення за вашою адресою
        {%- set end = state_attr('binary_sensor.kyiv_outage_at_address_now', 'end') %}
        {%- if end %} до {{ as_timestamp(end) | timestamp_custom('%H:%M') }}{% endif %}.
        {{ state_attr('binary_sensor.kyiv_outage_at_address_now', 'reason') or '' }}
```

## Розробка

Логіка графіка й зіставлення адрес — у модулях без залежності від Home
Assistant (`timeline.py`, `addressing.py`). Тести, зокрема спільні з сервером і
застосунками випадки `server/internal/outages/testdata/address_cases.json`:

```sh
cd homeassistant/tests
python3 -I -m unittest discover -s . -p "test_*.py"
```
