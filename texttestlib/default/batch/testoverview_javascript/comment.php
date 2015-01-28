<?php 

header('Content-Type: text/html; charset=UTF-8');

function existsEntry($id) {
	exec('egrep "^'.$id.'" comments.log | wc -l', $count);
	return strcmp($count[0], "1")==0;
}

function deleteEntry($id) {
	exec('egrep -v "^'.$id.'" comments.log > tmp.log');
	$commLines = "`cat comments.log | wc -l`";
	$tmpLines = "`cat tmp.log | wc -l`";
	exec('echo "'.$commLines.' - '.$tmpLines.'" | bc', $expectOne);
	if (strcmp($expectOne[0],"0")==0)
	{
	  exec('rm tmp.log');
	  die('{"err":"Comment already deleted/updated!"}');
        }
	if (strcmp($expectOne[0],"1")==0)
	{
	  exec('mv tmp.log comments.log');
	  chmod('comments.log', 0666);
	}
	else
	{
	  exec('rm tmp.log');
	  die('{"err":"Unexpected tmp file diff '.$expectOne[0]. ' not removing comment!"}');
	}	
}

function deleteComment($file, $id)
{
	$fileHandle = fopen($file, 'rw') 
	  or die ('{"err":"Could not write/read from file '.$file.'"}');
	deleteEntry($id);
	fclose($fileHandle);
}

function writeComment($file, $entry)
{
	$fileHandle = fopen($file, 'a') 
          or die ('{"err":"Could not write to file comments.log"}');

	fwrite($fileHandle, $entry . "\n");

	fclose($fileHandle);
	echo '{"ok":"Its all good"}';
}

function getComments($file, $dates_in)
{
	$dates = array();

        // 'precision' is the maximum length of all input date strings.
        // If an existing comment is associated with a date string
        // that is longer than 'precision', but the first 'precision'
        // characters match, it is included in the returned result.
        // This is used when a comment has time-of-day appended to the
        // date - then it matches even if we only throw in the right date.

	$precision = 0;

	foreach ($dates_in as $date) {
		$precision = max($precision, strlen($date));
		$dates[$date] = 1;
	}
	$fileHandle = fopen($file, 'r') 
	  or die ('{"err":"Could not read from file '.$file.'"}');

	echo '["';
	while ( ($entry = fgets($fileHandle)) !== false) {
		list($id, $dateTestsListStr, $rest) = split(";", $entry, 3);
		$dateTestsList = split("&", $dateTestsListStr); 
		for ($i = 0; $i < count($dateTestsList); $i++)
		{
		    list($date, $rest) = split("=", $dateTestsList[$i], 2);
	            if (array_key_exists( substr($date, 0, $precision) , $dates)) {
				echo str_replace("\n","",$entry) . '","';
				break;
			}
		}
	}
	echo '"]';
	fclose($fileHandle);
}

function updateComment($file, $id, $newEntry)
{
	$fileHandle = fopen($file, 'a') 
      	  or die ('{"err":"Could not write/read from file '.$file.'"}');
		
        if (existsEntry($id)) {
         	fwrite($fileHandle, $newEntry . "\n");	
	        deleteEntry($id);
        }
        else
	  die ('{"err":"The comment has already been deleted/edited."}');
	
	fclose($fileHandle);
}

function ensure_exists($f)
{
  // Create comments log file if it does not exist
  if (!file_exists($f))
    {
      touch($f);
      chmod($f, 0666);
    }
}

$lockfilename = ".lock";
ensure_exists($lockfilename);
$lockfile = fopen($lockfilename, 'r');

// Lock
if (!flock($lockfile, LOCK_EX))
  die('{"err":"Someone else is using the comments right now, try again later!"}');

$file = "comments.log";
ensure_exists($file);


if (strcmp($_POST['method'],"set")==0)
{
     writeComment($file, $_POST['entry']);
}
else if (strcmp(($_POST['method']),"get")==0)
{
     getComments($file, $_POST['dates']);
}
else if (strcmp(($_POST['method']),"delete")==0)
{
     deleteComment($file, $_POST['id']);
}
else if (strcmp(($_POST['method']),"update")==0)
{
     updateComment($file, $_POST['id'], $_POST['newentry']);
}
fclose($lockfile);
?>