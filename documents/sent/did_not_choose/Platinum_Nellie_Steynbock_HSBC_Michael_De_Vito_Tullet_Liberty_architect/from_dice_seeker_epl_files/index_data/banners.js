var hexVals = new Array("0","1","2","3","4","5","6","7","8","9","A","B","C","D","E","F");
var unsafeString = "\"<>%\\^[]`+&";

function loadDiceBanner(seekerDomain) {
    var x = top.location.href;
	var diceTopHREF = "http://" + seekerDomain + "/seeker.epl?rel_code=1102";
	var diceURLLength = 32 + seekerDomain.length;
	x = x.substr(0, diceURLLength);

    if (x == diceTopHREF) {
		top.HEADER_WIN.location.replace("/util/jobsearch/seekerHdr.html");
	}
}

function loadSeekerBanner(seekerDomain) {
    var x = top.location.href;
	var ranNum= Math.round(Math.random()*10000);
	var diceTopHREF = "http://" + seekerDomain + "/seeker.epl?rel_code=1102";
	var cnetTopHREF = "http://" + seekerDomain + "/seeker.epl?rel_code=1";
	var zdnetTopHREF = "http://" + seekerDomain + "/seeker.epl?rel_code=2";
	var diceURLLength = 32 + seekerDomain.length;
	x = x.substr(0, diceURLLength);
    if (x == diceTopHREF) {
		top.HEADER_WIN.location.replace("/seekerHdr.epl?tgt=job_tools&porkchop=" + ranNum);
	}
}

function targetSeekerBanner(seekerDomain, dartTgt) {
    var x = top.location.href;
	var ranNum= Math.round(Math.random()*10000);
	var diceTopHREF = "http://" + seekerDomain + "/seeker.epl?rel_code=1102";
	var cnetTopHREF = "http://" + seekerDomain + "/seeker.epl?rel_code=1";
	var zdnetTopHREF = "http://" + seekerDomain + "/seeker.epl?rel_code=2";
	var diceURLLength = 32 + seekerDomain.length;
	x = x.substr(0, diceURLLength);

    if (x == diceTopHREF) {
		var newHdr = "/seekerHdr.epl?tgt=" + dartTgt + "&porkchop=" + ranNum;
		top.HEADER_WIN.location.replace(newHdr);
	}
}

function metroTargetSeekerBanner(seekerDomain, dartTgt, kw) {
    var x = top.location.href;
	var ranNum= Math.round(Math.random()*10000);
	var diceTopHREF = "http://" + seekerDomain + "/seeker.epl?rel_code=1102";
	var cnetTopHREF = "http://" + seekerDomain + "/seeker.epl?rel_code=1";
	var zdnetTopHREF = "http://" + seekerDomain + "/seeker.epl?rel_code=2";
	var diceURLLength = 32 + seekerDomain.length;
	x = x.substr(0, diceURLLength);
	encKW = URLEncode(kw);

    if (x == diceTopHREF) {
		var newHdr = "/seekerHdr.epl?tgt=" + dartTgt + "&porkchop=" + ranNum + "&kw=" + encKW;
		top.HEADER_WIN.location.replace(newHdr);
	}
}

function loadKeywordBanner(seekerDomain, kw) {
    var x = top.location.href;
	var ranNum= Math.round(Math.random()*10000);
	var diceTopHREF = "http://" + seekerDomain + "/seeker.epl?rel_code=1102";
	var cnetTopHREF = "http://" + seekerDomain + "/seeker.epl?rel_code=1";
	var zdnetTopHREF = "http://" + seekerDomain + "/seeker.epl?rel_code=2";
	var diceURLLength = 32 + seekerDomain.length;
	x = x.substr(0, diceURLLength);

	encKW = URLEncode(kw);

    if (x == diceTopHREF) {
		var newHdr = "/seekerHdr.epl?tgt=job_tools&porkchop=" + ranNum + "&kw=" + encKW;
		top.HEADER_WIN.location.replace(newHdr);
	}
}

function URLEncode(val)
{
	var len     = val.length;
	var backlen = len;
	var i       = 0;

	var newStr  = "";
	var frag    = "";
	var encval  = "";

	for (i=0;i<len;i++) {
		if (isURLok(val.substring(i,i+1))) {
			newStr = newStr + val.substring(i,i+1);
		} else {
			tval1=val.substring(i,i+1);
			newStr = newStr + "%" + decToHex(tval1.charCodeAt(0),16);
		}

	}

	return newStr;
}

function decToHex(num, radix) // part of URL Encode
{
	var hexString = "";
	while (num >= radix) {
		temp = num % radix;
		num = Math.floor(num / radix);
		hexString += hexVals[temp];
	}

	hexString += hexVals[num];
	return reversal(hexString);
}

function reversal(s) // part of URL Encode
{
	var len = s.length;
	var trans = "";
	for (i=0; i<len; i++) {
		trans = trans + s.substring(len-i-1, len-i);
	}
	s = trans;
	return s;
}

function isURLok(compareChar) // part of URL Encode
{
	if (compareChar.charCodeAt(0) == 38) {
		return false;
	}
	if ((unsafeString.indexOf(compareChar) == -1) && 
			(compareChar.charCodeAt(0) > 32) && 
			(compareChar.charCodeAt(0) < 123)) {
		return true;
	} else {
		return false;
	}
}

var browserType = 'Z';
function loadFloatingAd() {
	if(document.all) {
		//Internet Explorer
		if (document.body.clientWidth > 795) {
			document.all.AdFloater.style.pixelLeft = (document.body.clientWidth)- 145; 
			document.all.AdFloater.style.visibility = 'visible';
			browserType = 'A';
		}
	}else if(document.layers) {
		//Opera??
		if (window.innerWidth > 795) {
			document.AdFloater.left = (window.innerWidth - 145);
			document.AdFloater.visibility = 'show';
			browserType = 'B';
		}	
	} else if(document.getElementById) {
		//Mozilla - Netscape
		if (window.innerWidth > 795) {
			document.getElementById('AdFloater').style.left = (window.innerWidth)-145;
			document.getElementById('AdFloater').style.visibility = 'visible';
			browserType = 'C';
		}
	}
	if (document.all) {
		window.onscroll = Float;
	} else {
		setInterval('Float()', 100);
	}
}

function Float() {
	if (browserType == 'A') {
		document.all.AdFloater.style.pixelTop = document.body.scrollTop;
	}
	else if (browserType == 'B') {
		document.AdFloater.top = window.pageYOffset;
	}
	else if (browserType == 'C') {
		document.getElementById('AdFloater').style.top = window.pageYOffset + 'px';
	}
}

