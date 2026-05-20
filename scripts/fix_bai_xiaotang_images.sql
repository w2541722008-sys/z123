-- 修复白小棠的头像和封面图片路径
-- 在线上服务器执行: psql $DATABASE_URL -f scripts/fix_bai_xiaotang_images.sql

UPDATE characters
SET avatar_url = '/frontend/assets/白小棠头像.jpg',
    cover_url = '/frontend/assets/白小棠封面.jpg'
WHERE id = 'bai_xiaotang';
