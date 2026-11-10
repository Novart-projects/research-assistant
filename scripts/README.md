# Запуск анализа

Из корня репозитория:

```bash
python -m pip install -r requirements-eda.txt
python scripts/collect_arxiv.py
```

Данные сохраняются в `data/`. Проверка кеша без загрузки: `python scripts/collect_arxiv.py --offline`.

Затем открыть `EDA.ipynb` в Jupyter или VS Code и выполнить все ячейки.
