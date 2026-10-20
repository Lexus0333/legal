# make_variants.sh

A/B-варианты ролика с разными хуками (текст в первые секунды) (надпись AI-generated по желанию: AI_LABEL="AI-generated").

    sh make_variants.sh input.mp4 out hooks.txt [trim_start_sec] [max_len_sec]

- hooks.txt: один хук в строке = один вариант (см. hooks.example.txt)
- На выходе: out/<имя>_vN.mp4 (1080x1920, H.264/AAC) и out/variants.csv (лог для таблицы)
- Шрифт: переменная FONT=путь.ttf. В контейнере n8n положите шрифт в infra/files/fonts/font.ttf
- Метаданные файла не стираем (в них может быть пометка о происхождении AI-контента)
- AI-метка ставится при публикации флагом платформы (is_aigc), не надписью в кадре
