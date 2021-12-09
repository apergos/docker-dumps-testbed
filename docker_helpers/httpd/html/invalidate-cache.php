<!DOCTYPE html>
<html lang=en>
    <meta charset="utf-8">
    <title>Opcache invalidation</title>
    <style>
        * { margin: 0; padding: 0; }
        body { background: #fff; margin: 7% auto 0; padding: 2em 1em 1em; font: 15px/1.6 sans-serif; color: #333; max-width: 640px; }
        img { float: left; margin: 0 2em 2em 0; }
        a img { border: 0; }
        h1 { margin-top: 1em; font-size: 1.2em; }
        h2 { font-size: 1em; }
        p { margin: 0.7em 0 1em 0; }
        a { color: #0645AD; text-decoration: none; }
        a:hover { text-decoration: underline; }
    </style>
	<body>
        <h1>PHP Opcache Invalidation</h1>
<?php
			opcache_reset();
			echo '<p>Opcache invalidated.</p>';
?> 
	</body>
</html>
